"""Google Maps links and coordinates: the parser, the short-link resolver and its endpoint.

No test touches the network: ``api.maps_link.fetch_location`` is replaced for
the resolver, and ``socket.getaddrinfo`` for the address guard.
"""
import socket
import threading
import time
from types import SimpleNamespace

import pytest

from api import maps_link
from utils import google_maps_link as gml

PIN_URL = ('https://www.google.com/maps/place/Pine+Valley/@32.8,-116.5,12z/'
           'data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d32.6064!4d-116.3239!16s')


@pytest.mark.parametrize('text, expected', [
    ('32.6064, -116.3239', (32.6064, -116.3239)),
    ('32.6064 -116.3239', (32.6064, -116.3239)),
    ('  -33.8688,151.2093  ', (-33.8688, 151.2093)),
    ('+32.6064; -116.3239', (32.6064, -116.3239)),
    ('32°36\'23.0"N 116°19\'26.0"W', (32 + 36 / 60 + 23 / 3600, -(116 + 19 / 60 + 26 / 3600))),
    ('33°51\'S, 151°12\'E', (-(33 + 51 / 60), 151 + 12 / 60)),
    ('32.6064° N, 116.3239° W', (32.6064, -116.3239)),
    ('116°19\'26"W 32°36\'23"N', (32 + 36 / 60 + 23 / 3600, -(116 + 19 / 60 + 26 / 3600))),
])
def test_free_text_pairs(text, expected):
    lat, lon = gml.parse_pair(text)
    assert lat == pytest.approx(expected[0], abs=1e-9)
    assert lon == pytest.approx(expected[1], abs=1e-9)


@pytest.mark.parametrize('text', [
    '', 'Pine Valley', '91, 10', '-90.5, 0', '10, 180.1', '10, -181',
    '32°61\'0"N 116°0\'0"W',  # minutes out of range
    '32°0\'0"N 116°0\'0"N',  # two latitudes
    '1, 2, 3', 'NaN, 1', '32.6064,', 'x' * 3000,
])
def test_free_text_refused(text):
    assert gml.parse_pair(text) is None


@pytest.mark.parametrize('url, expected', [
    (PIN_URL, (32.6064, -116.3239)),  # !3d!4d wins over @
    ('https://www.google.com/maps/@32.6064,-116.3239,15z', (32.6064, -116.3239)),
    ('https://www.google.com/maps/@32.6064,-116.3239,500m/data=!3m1!1e3', (32.6064, -116.3239)),
    ('https://maps.google.com/?q=32.6064,-116.3239', (32.6064, -116.3239)),
    ('https://maps.google.com/maps?q=loc:32.6064+-116.3239&z=10', (32.6064, -116.3239)),
    ('https://www.google.com/maps/search/?api=1&query=32.6064%2C-116.3239', (32.6064, -116.3239)),
    ('https://maps.google.com/?ll=32.6064,-116.3239&z=14', (32.6064, -116.3239)),
    ('https://www.google.com/maps/@?api=1&map_action=map&center=32.6064,-116.3239', (32.6064, -116.3239)),
    ('https://www.google.com/maps?q=1.5,2.5&ll=3,4', (1.5, 2.5)),  # q before ll
    ('https://www.google.com/maps/@5,6,10z?q=1,2', (1.0, 2.0)),  # q before @
    ('https://www.google.com/maps/search/32.6064,+-116.3239', (32.6064, -116.3239)),
    ('https://www.google.com/maps/place/32%C2%B036\'23.0%22N+116%C2%B019\'26.0%22W/',
     (32 + 36 / 60 + 23 / 3600, -(116 + 19 / 60 + 26 / 3600))),
    ('https://consent.google.com/m?continue=https://www.google.com/maps/%4032.6064,-116.3239,15z',
     (32.6064, -116.3239)),
    # Shared with google-maps-link.spec.ts: a stray % spoils no other escape,
    # the last pin wins, destination= counts, and a repeated key keeps its last value.
    ('https://www.google.com/maps/%4032.6064,-116.3239,15z?x=100%', (32.6064, -116.3239)),
    ('https://www.google.com/maps/place/X/data=!3d1.5!4d2.5!3d3.5!4d4.5', (3.5, 4.5)),
    ('https://www.google.com/maps/dir/?api=1&destination=32.6,-116.3', (32.6, -116.3)),
    ('https://www.google.com/maps/search/?api=1&q=1,2&q=3,4', (3.0, 4.0)),
])
def test_urls(url, expected):
    lat, lon = gml.parse_url(url)
    assert lat == pytest.approx(expected[0], abs=1e-9)
    assert lon == pytest.approx(expected[1], abs=1e-9)


@pytest.mark.parametrize('url', [
    'https://maps.app.goo.gl/AbCdEf123',
    'https://www.google.com/maps/place/Pine+Valley',
    'https://www.google.com/maps/@95,10,10z',
    'https://maps.google.com/?q=Pine+Valley',
])
def test_urls_without_a_point(url):
    assert gml.parse_url(url) is None


def test_malformed_wrapped_url_reads_as_no_point():
    # urlsplit raises ValueError on an unclosed IPv6 bracket inside a wrapped URL.
    assert gml.parse_url('https://maps.google.com/?q=http://[') is None


@pytest.mark.parametrize('url, ok', [
    ('https://maps.app.goo.gl/x', True),
    ('http://goo.gl/maps/x', True),
    ('https://www.google.com/maps', True),
    ('https://maps.app.goo.gl:8443/x', False),
    ('https://user:pw@maps.app.goo.gl/x', False),
    ('https://evil.example/maps', False),
    ('https://maps.app.goo.gl.evil.example/x', False),
    ('ftp://goo.gl/x', False),
    ('file:///etc/passwd', False),
    ('https:/\t/maps.app.goo.gl/x://evil.example/path', False),
    ('https://maps.app.goo.gl/x\n', False),
    ('https://maps.app.goo.gl/a b', False),
])
def test_allowlist(url, ok):
    assert maps_link.is_resolvable(url) is ok


@pytest.fixture
def hops(monkeypatch):
    """Scripted redirects; records every URL the resolver would have requested."""
    requested = []
    script = {}

    def fake(url, timeout):
        assert timeout <= maps_link.TIMEOUT_SECONDS
        requested.append(url)
        return script[url]

    monkeypatch.setattr(maps_link, 'fetch_location', fake)
    return requested, script


def test_short_link_followed_to_pin(hops):
    requested, script = hops
    script['https://maps.app.goo.gl/abc'] = (302, PIN_URL)
    assert maps_link.resolve('https://maps.app.goo.gl/abc') == (32.6064, -116.3239)
    # The Location carried the point, so it was parsed and never requested.
    assert requested == ['https://maps.app.goo.gl/abc']


def test_http_link_fetched_over_https(hops):
    requested, script = hops
    script['https://goo.gl/maps/abc'] = (301, 'https://maps.google.com/?q=1,2')
    assert maps_link.resolve('http://goo.gl/maps/abc') == (1.0, 2.0)
    assert requested == ['https://goo.gl/maps/abc']


def test_relative_and_chained_redirects(hops):
    requested, script = hops
    script['https://maps.app.goo.gl/abc'] = (302, 'https://www.google.com/maps/place/X')
    script['https://www.google.com/maps/place/X'] = (302, '/maps/@3.5,4.5,10z')
    assert maps_link.resolve('https://maps.app.goo.gl/abc') == (3.5, 4.5)
    assert len(requested) == 2


def test_redirect_off_allowlist_is_never_requested(hops):
    requested, script = hops
    script['https://maps.app.goo.gl/abc'] = (302, 'http://127.0.0.1:8080/admin')
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve('https://maps.app.goo.gl/abc')
    assert exc.value.code == 'unsupported_host'
    assert requested == ['https://maps.app.goo.gl/abc']


def test_foreign_host_refused_without_request(hops):
    requested, _ = hops
    for url in ('https://evil.example/x', 'http://169.254.169.254/latest/meta-data', 'not a url'):
        with pytest.raises(maps_link.LinkError) as exc:
            maps_link.resolve(url)
        assert exc.value.code == 'unsupported_host'
    assert requested == []


@pytest.mark.parametrize('url', [
    'https:/\t/maps.app.goo.gl/x://evil.example/path',
    'https:/\n/maps.app.goo.gl/x://evil.example/path',
    'https://maps.app.goo.gl/x\r://evil.example/path',
    'https://maps.app.goo.gl/x\x00',
])
def test_control_characters_are_refused_before_any_request(hops, url):
    requested, _ = hops
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve(url)
    assert exc.value.code == 'invalid_link'
    assert requested == []


def test_malformed_wrapped_url_is_refused_not_raised(hops):
    requested, script = hops
    script['https://maps.google.com/?q=http://['] = (200, None)
    for url in ('https://maps.google.com/?q=http://[', 'https://evil.example/?x=http://['):
        with pytest.raises(maps_link.LinkError):
            maps_link.resolve(url)
    assert requested == ['https://maps.google.com/?q=http://[']


@pytest.mark.parametrize('url', [123, None, 'x' * 2049])
def test_invalid_input(url):
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve(url)
    assert exc.value.code == 'invalid_link'


def test_deadline_passed_between_hops(monkeypatch, hops):
    requested, script = hops
    now = [0.0]
    monkeypatch.setattr(maps_link, 'time', SimpleNamespace(monotonic=lambda: now[0]))

    def first_hop_takes_the_whole_budget(url, timeout):
        requested.append(url)
        now[0] += maps_link.TIMEOUT_SECONDS + 1
        return 302, 'https://www.google.com/maps/place/X'
    monkeypatch.setattr(maps_link, 'fetch_location', first_hop_takes_the_whole_budget)
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve('https://maps.app.goo.gl/abc')
    assert exc.value.code == 'unreachable'
    assert requested == ['https://maps.app.goo.gl/abc']


def test_oversize_location_is_not_followed(hops):
    requested, script = hops
    script['https://maps.app.goo.gl/abc'] = (302, 'https://www.google.com/maps/' + 'x' * 5000)
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve('https://maps.app.goo.gl/abc')
    assert exc.value.code == 'no_coordinates'
    assert requested == ['https://maps.app.goo.gl/abc']


def test_hop_limit(hops):
    requested, script = hops
    for i in range(10):
        script[f'https://www.google.com/maps/p{i}'] = (302, f'https://www.google.com/maps/p{i + 1}')
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve('https://www.google.com/maps/p0')
    assert exc.value.code == 'too_many_redirects'
    assert len(requested) == maps_link.MAX_HOPS


def test_final_page_without_point(hops):
    _, script = hops
    script['https://maps.app.goo.gl/abc'] = (200, None)
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve('https://maps.app.goo.gl/abc')
    assert exc.value.code == 'no_coordinates'


def test_network_failure_is_unreachable(monkeypatch):
    def boom(url, timeout):
        raise TimeoutError
    monkeypatch.setattr(maps_link, 'fetch_location', boom)
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.resolve('https://maps.app.goo.gl/abc')
    assert exc.value.code == 'unreachable'


@pytest.mark.parametrize('addresses, ok', [
    (['142.250.72.14'], True),
    (['142.250.72.14', '10.0.0.5'], False),
    (['127.0.0.1'], False),
    (['169.254.169.254'], False),
    (['100.64.0.1'], False),
    (['::ffff:127.0.0.1'], False),
    (['64:ff9b::7f00:1'], False),
    (['224.0.0.1'], False),
])
def test_address_guard(monkeypatch, addresses, ok):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ':' in a else socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, port)) for a in addresses]
    monkeypatch.setattr(maps_link.socket, 'getaddrinfo', fake_getaddrinfo)
    if ok:
        assert maps_link.public_address('maps.app.goo.gl') == addresses[0]
    else:
        with pytest.raises(maps_link.LinkError) as exc:
            maps_link.public_address('maps.app.goo.gl')
        assert exc.value.code == 'unsupported_host'


@pytest.mark.parametrize('failure', ['gaierror', 'empty'])
def test_unresolvable_host_is_unreachable(monkeypatch, failure):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if failure == 'gaierror':
            raise socket.gaierror('no such host')
        return []
    monkeypatch.setattr(maps_link.socket, 'getaddrinfo', fake_getaddrinfo)
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.public_address('maps.app.goo.gl')
    assert exc.value.code == 'unreachable'


def test_slow_dns_stops_at_the_deadline(monkeypatch):
    def slow_getaddrinfo(host, port, *args, **kwargs):
        time.sleep(3)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('142.250.72.14', port))]
    monkeypatch.setattr(maps_link.socket, 'getaddrinfo', slow_getaddrinfo)
    started = time.monotonic()
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.public_address('maps.app.goo.gl', timeout=0.5)
    assert exc.value.code == 'unreachable'
    assert time.monotonic() - started < 2


class _StubTLS:
    """Stands in for the TLS context: records the SNI name, hands back the plain socket."""

    def __init__(self, fail=False):
        self.server_hostname = None
        self.fail = fail

    def wrap_socket(self, sock, server_hostname=None, **kwargs):
        self.server_hostname = server_hostname
        if self.fail:
            raise OSError('handshake failed')
        return sock


@pytest.fixture
def pinned(monkeypatch):
    """getaddrinfo answers a public address; connections are redirected to a local test server."""
    state = SimpleNamespace(connected_to=[], tls=_StubTLS(), port=None, raw=[])
    monkeypatch.setattr(maps_link.socket, 'getaddrinfo', lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('142.250.72.14', port))])
    def create(address, timeout=None, *args, **kwargs):
        state.connected_to.append(address)
        # Not socket.create_connection: it would resolve through the patched getaddrinfo.
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(timeout)
        raw.connect(('127.0.0.1', state.port))
        state.raw.append(raw)
        return raw
    monkeypatch.setattr(maps_link.socket, 'create_connection', create)
    monkeypatch.setattr(maps_link.ssl, 'create_default_context', lambda *a, **k: state.tls)
    return state


def _serve(handler):
    """One-connection local server running ``handler(conn)`` on a thread; returns (port, stop)."""
    listener = socket.create_server(('127.0.0.1', 0))
    stop = threading.Event()

    def run():
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        with conn:
            conn.recv(4096)
            handler(conn, stop)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    def close():
        stop.set()
        listener.close()
        thread.join(5)
    return listener.getsockname()[1], close


def test_fetch_connects_to_the_checked_address_with_the_hostname_for_tls(pinned):
    def redirect(conn, stop):
        conn.sendall(b'HTTP/1.1 302 Found\r\nLocation: https://maps.google.com/?q=1,2\r\nContent-Length: 0\r\n\r\n')
    pinned.port, close = _serve(redirect)
    try:
        assert maps_link.fetch_location('https://maps.app.goo.gl/abc', 2.0) == (302, 'https://maps.google.com/?q=1,2')
    finally:
        close()
    assert pinned.connected_to == [('142.250.72.14', 443)]
    assert pinned.tls.server_hostname == 'maps.app.goo.gl'


def test_fetch_never_connects_to_a_private_address(monkeypatch, pinned):
    monkeypatch.setattr(maps_link.socket, 'getaddrinfo', lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.5', port))])
    with pytest.raises(maps_link.LinkError) as exc:
        maps_link.fetch_location('https://maps.app.goo.gl/abc', 2.0)
    assert exc.value.code == 'unsupported_host'
    assert pinned.connected_to == []


def test_fetch_closes_the_socket_when_tls_fails(pinned):
    pinned.tls.fail = True
    pinned.port, close = _serve(lambda conn, stop: stop.wait(2))
    try:
        with pytest.raises(OSError):
            maps_link.fetch_location('https://maps.app.goo.gl/abc', 2.0)
    finally:
        close()
    assert pinned.raw and pinned.raw[0].fileno() == -1


def test_trickling_server_is_cut_at_the_deadline(monkeypatch, pinned):
    monkeypatch.setattr(maps_link, 'TIMEOUT_SECONDS', 1.0)

    def trickle(conn, stop):
        conn.sendall(b'HTTP/1.1 302 Found\r\n')
        while not stop.wait(0.3):
            try:
                conn.sendall(b'X-Slow: 1\r\n')
            except OSError:
                return
    pinned.port, close = _serve(trickle)
    started = time.monotonic()
    try:
        with pytest.raises(maps_link.LinkError) as exc:
            maps_link.resolve('https://maps.app.goo.gl/abc')
    finally:
        close()
    assert exc.value.code == 'unreachable'
    assert time.monotonic() - started < 2.5


def test_endpoint_answers_422_for_a_malformed_wrapped_url(edition_client, hops):
    _, script = hops
    script['https://maps.google.com/?q=http://['] = (200, None)
    resp = edition_client.post('/api/geo/resolve_maps_link', json={'url': 'https://maps.google.com/?q=http://['})
    assert resp.status_code == 422


def test_endpoint_resolves(edition_client, hops):
    _, script = hops
    script['https://maps.app.goo.gl/abc'] = (302, PIN_URL)
    resp = edition_client.post('/api/geo/resolve_maps_link', json={'url': 'https://maps.app.goo.gl/abc'})
    assert resp.status_code == 200
    assert resp.json() == {'latitude': 32.6064, 'longitude': -116.3239}


def test_endpoint_refuses_foreign_host(edition_client, hops):
    requested, _ = hops
    resp = edition_client.post('/api/geo/resolve_maps_link', json={'url': 'https://evil.example/x'})
    assert resp.status_code == 422
    assert resp.json()['detail'] == 'unsupported_host'
    assert requested == []


def test_endpoint_validates_body(edition_client, hops):
    assert edition_client.post('/api/geo/resolve_maps_link', json={'url': ''}).status_code == 422
    assert edition_client.post('/api/geo/resolve_maps_link', json={'url': 'x' * 2049}).status_code == 422


def test_endpoint_is_edition_only(regular_client, anonymous_client, hops):
    requested, _ = hops
    body = {'url': 'https://maps.app.goo.gl/abc'}
    assert regular_client.post('/api/geo/resolve_maps_link', json=body).status_code in (401, 403)
    assert anonymous_client.post('/api/geo/resolve_maps_link', json=body).status_code in (401, 403)
    assert requested == []
