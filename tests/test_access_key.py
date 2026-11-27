"""api/access_key.py: with the macOS app's key set, only the browser the app opened, and the app, reach the viewer."""

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

import json
from pathlib import Path

from api.access_key import ACCESS_KEY_COOKIE, ACCESS_KEY_ENV, ACCESS_KEY_HEADER, LAUNCH_PATH, PUBLIC_PATHS, AccessKeyGate

KEY = 'k' * 43


@pytest.fixture
def client():
    app = FastAPI()

    @app.get('/api/photos')
    def photos():
        return {'photos': []}

    @app.post('/mcp')
    def mcp():
        return {'mcp': True}

    @app.websocket('/api/mcp/bridge')
    async def bridge(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text('hello')
        await websocket.close()

    app.add_middleware(AccessKeyGate, key=KEY, open_paths=('/mcp',))
    return TestClient(app, base_url='http://127.0.0.1:5019')


def test_a_request_without_the_key_is_refused(client):
    response = client.get('/api/photos')
    assert response.status_code == 403
    assert 'menu bar' in response.json()['detail']


def test_a_wrong_key_is_refused_everywhere_it_could_come_from(client):
    assert client.get('/api/photos', headers={ACCESS_KEY_HEADER: 'nope'}).status_code == 403
    response = client.get(f'{LAUNCH_PATH}?access_key=nope', follow_redirects=False)
    assert response.status_code == 403 and 'set-cookie' not in response.headers
    client.cookies.set(ACCESS_KEY_COOKIE, 'nope')
    assert client.get('/api/photos').status_code == 403


def test_the_launch_link_trades_the_key_for_a_cookie_and_drops_it_from_the_address(client):
    response = client.get(f'{LAUNCH_PATH}?access_key={KEY}', follow_redirects=False)
    assert response.status_code == 303
    assert response.headers['location'] == '/'
    cookie = response.headers['set-cookie']
    assert cookie.startswith(f'{ACCESS_KEY_COOKIE}={KEY};')
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/' in cookie
    assert client.get('/api/photos').status_code == 200, 'the browser now holds the cookie'


def test_the_location_ignores_the_host_header(client):
    response = client.get(f'{LAUNCH_PATH}?access_key={KEY}', headers={'host': 'evil.example'}, follow_redirects=False)
    assert response.headers['location'] == '/'


def test_the_key_counts_only_on_the_launch_path(client):
    # Anywhere else it would be a second way in that skips the redirect.
    assert client.get(f'/api/photos?access_key={KEY}').status_code == 403


def test_the_service_worker_never_answers_the_launch_path():
    # ngsw serves a cached index.html for every navigation it matches, and such a request
    # never reaches the viewer, so the cookie would never be set.
    config = json.loads((Path(__file__).resolve().parent.parent / 'client' / 'ngsw-config.json').read_text())
    assert '!/api/**' in config['navigationUrls'] and LAUNCH_PATH.startswith('/api/')


def test_the_app_itself_sends_the_header(client):
    assert client.get('/api/photos', headers={ACCESS_KEY_HEADER: KEY}).status_code == 200


def test_mcp_keeps_its_own_token_gate(client):
    assert client.post('/mcp').status_code == 200


def test_the_manifest_and_its_icons_load_without_the_cookie():
    # A manifest is fetched without credentials, so a refused one breaks the installed app.
    manifest = Path(__file__).resolve().parent.parent / 'client' / 'public' / 'manifest.webmanifest'
    names = {'/' + manifest.name} | {'/' + icon['src'] for icon in json.loads(manifest.read_text())['icons']}
    assert names == PUBLIC_PATHS


def test_a_public_path_passes_without_the_key():
    app = FastAPI()

    @app.get('/manifest.webmanifest')
    def manifest():
        return {}

    app.add_middleware(AccessKeyGate, key=KEY)
    assert TestClient(app).get('/manifest.webmanifest').status_code == 200


def test_a_browser_is_told_in_its_language(client):
    response = client.get('/', headers={'accept': 'text/html', 'accept-language': 'fr-FR,fr;q=0.9'})
    assert response.status_code == 403
    assert response.headers['content-type'].startswith('text/html')
    assert '<html lang="fr">' in response.text and 'menu' in response.text


def test_a_websocket_needs_the_cookie(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/mcp/bridge') as ws:
            ws.receive_text()
    client.cookies.set(ACCESS_KEY_COOKIE, KEY)
    with client.websocket_connect('/api/mcp/bridge') as ws:
        assert ws.receive_text() == 'hello'


def test_the_viewer_installs_the_gate_only_when_the_app_sets_the_key(monkeypatch):
    from api import create_app
    monkeypatch.setenv(ACCESS_KEY_ENV, KEY)
    gated = TestClient(create_app())
    assert gated.get('/api/i18n/languages').status_code == 403
    assert gated.get('/api/i18n/languages', headers={ACCESS_KEY_HEADER: KEY}).status_code == 200
    monkeypatch.delenv(ACCESS_KEY_ENV)
    assert TestClient(create_app()).get('/api/i18n/languages').status_code == 200


def test_the_assistant_tools_reach_the_api_through_the_gate(monkeypatch):
    # The MCP tools call the viewer's own routes in process, back through this middleware.
    import asyncio
    from api import create_app
    from api.agent import tokens
    from api.agent.internal_client import InternalClient, RouteSpec

    class Grant:
        def resolve(self):
            return self

        level = tokens.LEVELS[-1]

        def jwt_claims(self):
            return None

    monkeypatch.setenv(ACCESS_KEY_ENV, KEY)
    client = InternalClient(create_app(), allowlist={'languages': RouteSpec('GET', '/api/i18n/languages', 'readonly')})
    result = asyncio.run(client.call(Grant(), 'languages'))
    assert result['ok'] is True, result
