"""Small, explicit Photon lookup. No query or outbound URL is logged here.

Cache and throttle are per viewer process; deploy one worker or use a private
Photon instance when sharing an installation across multiple workers.
"""
import http.client
import json
import socket
import ssl
import threading
import time
import zlib
from collections import OrderedDict
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException

from api.config import VIEWER_CONFIG

_MAX_BYTES = 65536
_TIMEOUT_SECONDS = 5.0
_cache: OrderedDict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = OrderedDict()
_lock = threading.Lock()
_next_request = 0.0
_inflight = False


def endpoint() -> str:
    """Only the operator can choose a server. Never expose its URL/credentials."""
    value = VIEWER_CONFIG.get('place_search_url', '')
    if not isinstance(value, str) or not value or len(value) > 2000 or any(ord(c) < 33 for c in value):
        return ''
    try:
        url = urlsplit(value)
        if url.scheme not in ('https', 'http') or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment:
            return ''
        _ = url.port
    except ValueError:
        return ''
    return value


class _DeadlineConnection(http.client.HTTPConnection):
    """Keep the active socket reachable while HTTP parsing owns a file wrapper.

    A watchdog shuts it down at the total deadline, interrupting blocking
    headers/chunk framing as well as reads. Native DNS resolution is synchronous
    and cannot be interrupted; after it returns, expiry forbids opening a socket.
    """

    def __init__(self, endpoint_url: str, deadline: float):
        url = urlsplit(endpoint_url)
        if not url.hostname:
            raise ValueError('Invalid endpoint')
        self._secure = url.scheme == 'https'
        self._deadline = deadline
        self._socket_lock = threading.Lock()
        self._active_socket: socket.socket | None = None
        self.expired = False
        super().__init__(url.hostname, url.port or (443 if self._secure else 80), timeout=_TIMEOUT_SECONDS)

    def remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if self.expired or remaining <= 0:
            raise TimeoutError
        return remaining

    def expire(self) -> None:
        with self._socket_lock:
            self.expired = True
            active = self._active_socket
        if active is not None:
            # close() alone need not wake a thread blocked in recv on a socket
            # file object. shutdown() interrupts the underlying operation first.
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            active.close()

    def connect(self) -> None:
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        self.remaining()
        last_error: OSError | None = None
        for family, kind, protocol, _, address in addresses:
            active = socket.socket(family, kind, protocol)
            try:
                with self._socket_lock:
                    active.settimeout(self.remaining())
                    self._active_socket = active
                    self.sock = active
                active.connect(address)
                if self._secure:
                    context = ssl.create_default_context()
                    with self._socket_lock:
                        self.remaining()
                        secure = context.wrap_socket(active, server_hostname=self.host, do_handshake_on_connect=False)
                        self._active_socket = secure
                        self.sock = secure
                    secure.settimeout(self.remaining())
                    secure.do_handshake()
                self.remaining()
                return
            except OSError as exc:
                if self.sock is not None:
                    self.sock.close()
                active.close()
                self.sock = None
                last_error = exc
                self.remaining()
        if last_error is not None:
            raise last_error
        raise OSError('No provider address')

    def finish(self) -> None:
        # HTTPConnection.close() can run as soon as Connection: close headers
        # arrive, while its response still owns the readable socket file. Keep
        # our reference until the fetch finishes so the watchdog can wake it.
        super().close()
        with self._socket_lock:
            active = self._active_socket
            self._active_socket = None
        if active is not None:
            active.close()


def _fetch(endpoint_url: str, query: str) -> Any:
    """No redirects or retries; cap both wire and decoded bytes, including gzip."""
    url = urlsplit(endpoint_url)
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    conn = _DeadlineConnection(endpoint_url, deadline)
    watchdog = threading.Timer(_TIMEOUT_SECONDS, conn.expire)
    watchdog.name = 'facet-place-search-deadline'
    watchdog.start()
    response: http.client.HTTPResponse | None = None
    try:
        path = (url.path or '/') + '?' + urlencode({'q': query, 'limit': 5})
        conn.request('GET', path, headers={'User-Agent': 'Facet-place-search/1.0 (https://github.com/ncoevoet/facet)', 'Accept': 'application/json', 'Accept-Encoding': 'gzip'})
        read_socket = conn.sock
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        if read_socket is not None:
            read_socket.settimeout(remaining)
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError('Provider unavailable')
        encoding = response.getheader('Content-Encoding', 'identity').lower()
        if encoding not in ('identity', 'gzip'):
            raise ValueError('Unsupported encoding')
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == 'gzip' else None
        data = bytearray()
        wire_size = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if read_socket is not None:
                read_socket.settimeout(remaining)
            chunk = response.read1(8192)
            if not chunk:
                break
            wire_size += len(chunk)
            if wire_size > _MAX_BYTES:
                raise ValueError('Response too large')
            data.extend(decoder.decompress(chunk, _MAX_BYTES + 1 - len(data)) if decoder else chunk)
            if len(data) > _MAX_BYTES or (decoder and decoder.unconsumed_tail):
                raise ValueError('Response too large')
        if decoder and (not decoder.eof or decoder.unused_data):
            raise ValueError('Invalid compressed response')
        return json.loads(data)
    except (OSError, http.client.HTTPException, ValueError):
        if conn.expired:
            raise TimeoutError from None
        raise
    finally:
        watchdog.cancel()
        if response is not None:
            response.close()
        conn.finish()
        watchdog.join()


def _results(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
        return []
    results = []
    for item in data['features']:
        if not isinstance(item, dict) or item.get('type') != 'Feature':
            continue
        geometry, props = item.get('geometry'), item.get('properties')
        if not isinstance(geometry, dict) or geometry.get('type') != 'Point' or not isinstance(props, dict):
            continue
        coords = geometry.get('coordinates')
        if not isinstance(coords, list) or len(coords) != 2:
            continue
        if any(type(n) not in (float, int) for n in coords):
            continue
        lon, lat = coords
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            continue
        parts = []
        invalid = False
        for key in ('name', 'housenumber', 'street', 'postcode', 'city', 'state', 'country'):
            value = props.get(key)
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > 300 or any(ord(c) < 32 for c in value):
                invalid = True
                break
            value = value.strip()
            if value and value not in parts:
                parts.append(value)
        label = ', '.join(parts)
        if invalid or not label or len(label) > 600:
            continue
        results.append({'label': label, 'latitude': lat, 'longitude': lon})
        if len(results) == 5:
            break
    return results


def search(query: str) -> list[dict[str, Any]]:
    global _next_request, _inflight
    if len(query) > 200:
        raise HTTPException(422, 'Search must contain 3 to 200 characters')
    query = query.strip()
    if not 3 <= len(query) <= 200 or any(ord(c) < 32 for c in query):
        raise HTTPException(422, 'Search must contain 3 to 200 characters')
    url = endpoint()
    if not url:
        raise HTTPException(503, 'Online place search is disabled')
    # Do not queue unbounded work. Reserve the provider interval before the call;
    # a busy search refuses new misses while cached searches remain available.
    key = (url, query)
    with _lock:
        now = time.monotonic()
        for expired in [k for k, (stamp, _) in _cache.items() if now - stamp >= 900]:
            del _cache[expired]
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key][1]
        if _inflight or now < _next_request:
            raise HTTPException(429, 'Wait before searching again', headers={'Retry-After': '1'})
        _inflight = True
    try:
        results = _results(_fetch(url, query))
    except (OSError, ValueError, http.client.HTTPException, zlib.error):
        raise HTTPException(502, 'Online place search is unavailable') from None
    finally:
        with _lock:
            _next_request = time.monotonic() + 1
            _inflight = False
    with _lock:
        _cache[key] = (time.monotonic(), results)
        while len(_cache) > 128:
            _cache.popitem(last=False)
    return results
