"""Google Maps links and coordinates: the parser, the short-link resolver and its endpoint.

No test touches the network: ``api.maps_link.fetch_location`` is replaced for
the resolver, and ``socket.getaddrinfo`` for the address guard.
"""
import socket

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
    lat, lon = gml.parse(text)
    assert lat == pytest.approx(expected[0], abs=1e-9)
    assert lon == pytest.approx(expected[1], abs=1e-9)


@pytest.mark.parametrize('text', [
    '', 'Pine Valley', '91, 10', '-90.5, 0', '10, 180.1', '10, -181',
    '32°61\'0"N 116°0\'0"W',  # minutes out of range
    '32°0\'0"N 116°0\'0"N',  # two latitudes
    '1, 2, 3', 'NaN, 1', '32.6064,', 'x' * 3000,
])
def test_free_text_refused(text):
    assert gml.parse(text) is None


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
])
def test_urls(url, expected):
    lat, lon = gml.parse(url)
    assert lat == pytest.approx(expected[0], abs=1e-9)
    assert lon == pytest.approx(expected[1], abs=1e-9)


@pytest.mark.parametrize('url', [
    'https://maps.app.goo.gl/AbCdEf123',
    'https://www.google.com/maps/place/Pine+Valley',
    'https://www.google.com/maps/@95,10,10z',
    'https://maps.google.com/?q=Pine+Valley',
])
def test_urls_without_a_point(url):
    assert gml.parse(url) is None


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
