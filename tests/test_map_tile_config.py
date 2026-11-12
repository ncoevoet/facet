"""The self-hosted basemap config: what /api/config surfaces and what it refuses."""

import pytest
from unittest.mock import patch

import api.config
from api.config import VIEWER_CONFIG


@pytest.fixture()
def map_tile(monkeypatch):
    def configure(url, attribution='', max_zoom=19):
        monkeypatch.setitem(VIEWER_CONFIG, 'map_tile_url', url)
        monkeypatch.setitem(VIEWER_CONFIG, 'map_tile_attribution', attribution)
        monkeypatch.setitem(VIEWER_CONFIG, 'map_tile_max_zoom', max_zoom)
    return configure


def test_default_config_surfaces_the_osm_fallback(client, monkeypatch):
    # The repo-root config is developer-owned; the defaults come from the code.
    for key in ('map_tile_url', 'map_tile_attribution', 'map_tile_max_zoom'):
        monkeypatch.delitem(VIEWER_CONFIG, key, raising=False)
    body = client.get('/api/config').json()
    assert body['map_tile_url'] == ''
    assert body['map_tile_attribution'] == ''
    assert body['map_tile_max_zoom'] == 19


def test_same_origin_path_is_surfaced_verbatim(client, map_tile):
    map_tile('/tiles/{z}/{x}/{y}.png', attribution='&copy; Nas', max_zoom=20)
    body = client.get('/api/config').json()
    assert body['map_tile_url'] == '/tiles/{z}/{x}/{y}.png'
    assert body['map_tile_attribution'] == '&copy; Nas'
    assert body['map_tile_max_zoom'] == 20


def test_https_url_is_surfaced(client, map_tile):
    map_tile('https://tiles.example/{z}/{x}/{y}.png')
    assert client.get('/api/config').json()['map_tile_url'] == 'https://tiles.example/{z}/{x}/{y}.png'


def test_http_absolute_url_is_refused_the_csp_would_block_it(client, map_tile):
    # img-src permits 'self' and https: only; an http:// URL would silently
    # render a grey map in every browser, so the endpoint returns the OSM
    # default instead of a value it knows cannot work.
    map_tile('http://nas.local:8080/tiles/{z}/{x}/{y}.png')
    body = client.get('/api/config').json()
    assert body['map_tile_url'] == ''


def test_non_http_schemes_are_refused(client, map_tile):
    map_tile('ftp://tiles.example/{z}/{x}/{y}.png')
    assert client.get('/api/config').json()['map_tile_url'] == ''
    map_tile('javascript:alert(1)')
    assert client.get('/api/config').json()['map_tile_url'] == ''


def test_whitespace_only_url_falls_back_to_the_osm_default(client, map_tile):
    map_tile('   ')
    assert client.get('/api/config').json()['map_tile_url'] == ''


def test_protocol_relative_url_is_refused(client, map_tile):
    # '//' is cross-origin, not the same-origin path the config promises, and
    # on http-served installs the CSP would block it (no http: token).
    map_tile('//nas.local:8080/tiles/{z}/{x}/{y}.png')
    assert client.get('/api/config').json()['map_tile_url'] == ''


def test_url_without_coordinate_placeholders_is_refused(client, map_tile):
    # Leaflet throws synchronously on an unknown template key and cannot render
    # without {z}/{x}/{y}; refuse both shapes at the endpoint.
    map_tile('https://tiles.example/flat.png')
    assert client.get('/api/config').json()['map_tile_url'] == ''
    map_tile('/tiles/{z}/{x}/weird.png')
    assert client.get('/api/config').json()['map_tile_url'] == ''


def test_empty_netloc_and_credentialed_urls_are_refused(client, map_tile):
    # Browsers reject empty-authority https URLs, and a credentialed URL would
    # leak those credentials to every pre-auth /api/config reader.
    map_tile('https:///tiles/{z}/{x}/{y}.png')
    assert client.get('/api/config').json()['map_tile_url'] == ''
    map_tile('https://user:pass@tiles.example/{z}/{x}/{y}.png')
    assert client.get('/api/config').json()['map_tile_url'] == ''


def test_non_string_attribution_falls_back_to_empty(client, map_tile):
    # The response model declares str; a raw non-string would fail the /api/config
    # response validation on every request instead of degrading.
    map_tile('/tiles/{z}/{x}/{y}.png')
    with patch.object(api.config, 'VIEWER_CONFIG', {**api.config.VIEWER_CONFIG, 'map_tile_attribution': 5}):
        assert client.get('/api/config').json()['map_tile_attribution'] == ''


def test_url_with_an_unknown_placeholder_is_refused(client, map_tile):
    # Leaflet throws synchronously on an unknown template key, killing the map
    # surface; only its own variables are allowed through.
    map_tile('/tiles/{z}/{x}/{y}/{quadkey}.png')
    assert client.get('/api/config').json()['map_tile_url'] == ''
    map_tile('/tiles/{z}/{x}/{y}/{r}.png')  # Leaflet's retina placeholder is fine
    assert client.get('/api/config').json()['map_tile_url'] == '/tiles/{z}/{x}/{y}/{r}.png'


def test_max_zoom_nan_and_infinity_fall_back_to_the_default(client, map_tile):
    # json.load accepts NaN/Infinity and int() of those raises.
    map_tile('/tiles/{z}/{x}/{y}.png', max_zoom=float('nan'))
    assert client.get('/api/config').json()['map_tile_max_zoom'] == 19
    map_tile('/tiles/{z}/{x}/{y}.png', max_zoom=float('inf'))
    assert client.get('/api/config').json()['map_tile_max_zoom'] == 19
    map_tile('/tiles/{z}/{x}/{y}.png', max_zoom=1e309)
    assert client.get('/api/config').json()['map_tile_max_zoom'] == 19


def test_max_zoom_is_guarded_against_unparseable_and_absurd_values(client, map_tile):
    # The JSON-schema integer constraint is advisory: a bad value must not 500
    # the SPA's startup endpoint, and absurd values must not feed Leaflet.
    map_tile('/tiles/{z}/{x}/{y}.png', max_zoom='twenty')
    assert client.get('/api/config').json()['map_tile_max_zoom'] == 19
    map_tile('/tiles/{z}/{x}/{y}.png', max_zoom=10 ** 9)
    assert client.get('/api/config').json()['map_tile_max_zoom'] == 30
    map_tile('/tiles/{z}/{x}/{y}.png', max_zoom=-5)
    assert client.get('/api/config').json()['map_tile_max_zoom'] == 0
    map_tile('/tiles/{z}/{x}/{y}.png', max_zoom=True)  # int(True) == 1
    assert client.get('/api/config').json()['map_tile_max_zoom'] == 19
