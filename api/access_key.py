"""The macOS app's access key: only a browser the app opened, and the app itself, reach the viewer.

The app keeps a per-install key in a file only its user can read and starts the viewer with it in
``FACET_ACCESS_KEY``. It opens the gallery once as ``/?access_key=<key>``; the viewer answers with a
cookie and a redirect that drops the key from the address bar, and the app's own requests send the
``X-Facet-Access-Key`` header. Anything else is refused: another account on the Mac, a page that
rebinds its domain to 127.0.0.1 (its requests carry its own Host, so never the cookie), or a local
tool that does not read the key. ``/mcp`` (``open_paths``) is left to its own bearer-token gate, so a local assistant
keeps working. Without the variable (a terminal, Docker, a NAS) nothing changes.
"""

import hmac
from html import escape
from urllib.parse import urlencode

from starlette.requests import HTTPConnection
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from api.routers.i18n import _load_translations
from i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES

ACCESS_KEY_ENV = 'FACET_ACCESS_KEY'
ACCESS_KEY_QUERY = 'access_key'
ACCESS_KEY_HEADER = 'x-facet-access-key'
ACCESS_KEY_COOKIE = 'facet_access'
# Chrome caps a cookie's lifetime at 400 days.
COOKIE_MAX_AGE = 400 * 24 * 3600
REFUSAL_PATH = ('macos_app', 'server', 'open_from_menu')
# Browsers fetch the web-app manifest, and the icons it names, without cookies; none holds anything private.
PUBLIC_PATHS = frozenset({'/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/icon-maskable-512.png'})


def _language(accept_language: str) -> str:
    for part in accept_language.split(','):
        code = part.split(';')[0].strip()[:2].lower()
        if code in SUPPORTED_LANGUAGES:
            return code
    return DEFAULT_LANGUAGE


def _text(lang: str) -> str:
    node: object = _load_translations(lang)
    for part in REFUSAL_PATH:
        node = node.get(part) if isinstance(node, dict) else None
    return node if isinstance(node, str) else ''


def _refusal_text(accept_language: str) -> tuple[str, str]:
    lang = _language(accept_language)
    return lang, _text(lang) or _text(DEFAULT_LANGUAGE)


class AccessKeyGate:
    def __init__(self, app: ASGIApp, key: str, open_paths: tuple[str, ...] = ()):
        self.app = app
        self.key = key
        self.open_paths = open_paths

    def _matches(self, given) -> bool:
        return isinstance(given, str) and hmac.compare_digest(given.encode(), self.key.encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] not in ('http', 'websocket') or scope['path'] in self.open_paths \
                or scope['path'] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        conn = HTTPConnection(scope)
        if scope['type'] == 'http' and self._matches(conn.query_params.get(ACCESS_KEY_QUERY)):
            # Relative, so the Host header never picks where the browser goes next.
            rest = urlencode([(k, v) for k, v in conn.query_params.multi_items() if k != ACCESS_KEY_QUERY])
            response = RedirectResponse(scope['path'] + (f'?{rest}' if rest else ''), status_code=303)
            response.set_cookie(ACCESS_KEY_COOKIE, self.key, max_age=COOKIE_MAX_AGE, path='/',
                                httponly=True, samesite='lax')
            await response(scope, receive, send)
            return
        if self._matches(conn.cookies.get(ACCESS_KEY_COOKIE)) or self._matches(conn.headers.get(ACCESS_KEY_HEADER)):
            await self.app(scope, receive, send)
            return
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        lang, text = _refusal_text(conn.headers.get('accept-language', ''))
        if 'text/html' in conn.headers.get('accept', ''):
            page = (f'<!doctype html><html lang="{lang}"><meta charset="utf-8"><title>Facet</title>'
                    f'<p style="font:16px system-ui;margin:3em auto;max-width:32em">{escape(text)}</p></html>')
            response = HTMLResponse(page, status_code=403)
        else:
            response = JSONResponse({'detail': text}, status_code=403)
        await response(scope, receive, send)
