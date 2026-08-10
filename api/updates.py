"""Upstream release check: is a newer Facet published than the one running?

Deliberately server-side and cached. One install asks GitHub at most once per
`interval_days` however many people are looking at the viewer, the request
carries nothing but itself (no token, no library data, no identifiers), and a
failure is silent -- an unreachable GitHub must never be visible in the UI as an
error, only as "no update known".

Distinct from the service worker's own "new version is available", which is
about reloading the page onto an already-downloaded bundle. This one is about a
release the operator has not installed yet.
"""

import json
import logging
import time
import urllib.error
import urllib.request

from utils.version import current_version, is_newer

logger = logging.getLogger("facet.updates")

CACHE_KEY = 'update_check'
DEFAULT_URL = 'https://api.github.com/repos/ncoevoet/facet/releases/latest'
DEFAULT_INTERVAL_DAYS = 7
REQUEST_TIMEOUT_SECONDS = 5


def get_update_settings():
    """`updates` block from scoring_config.json, with safe defaults."""
    try:
        from api.config import _FULL_CONFIG
        settings = (_FULL_CONFIG.get('updates') or {})
    except (ImportError, AttributeError):
        settings = {}
    return {
        'enabled': settings.get('enabled', True),
        'check_url': settings.get('check_url', DEFAULT_URL),
        'interval_days': settings.get('interval_days', DEFAULT_INTERVAL_DAYS),
    }


def _fetch_latest(url):
    """Latest release tag + page URL, or None when upstream cannot be reached."""
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'facet-update-check',
    })
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as ex:
        logger.info("Update check could not reach %s: %s", url, ex)
        return None
    tag = payload.get('tag_name') or payload.get('name')
    if not tag:
        return None
    return {'latest': str(tag), 'release_url': payload.get('html_url') or ''}


def check_for_update(conn, force=False):
    """Whether a newer release exists, answering from cache within the interval.

    The timestamp is written even when the fetch fails, so an install with no
    outbound network retries once per interval rather than on every request.
    """
    current = current_version()
    settings = get_update_settings()
    if not settings['enabled']:
        return {'enabled': False, 'current': current, 'latest': None,
                'update_available': False, 'release_url': ''}

    cached = conn.execute(
        "SELECT value, updated_at FROM stats_cache WHERE key = ?", (CACHE_KEY,)
    ).fetchone()
    max_age = settings['interval_days'] * 86400
    if cached and not force and (time.time() - (cached['updated_at'] or 0)) < max_age:
        try:
            stored = json.loads(cached['value'])
        except (json.JSONDecodeError, TypeError):
            stored = None
        if stored is not None:
            return _result(current, stored)

    fetched = _fetch_latest(settings['check_url']) or {'latest': None, 'release_url': ''}
    conn.execute(
        "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
        (CACHE_KEY, json.dumps(fetched), time.time()),
    )
    conn.commit()
    return _result(current, fetched)


def _result(current, stored):
    latest = stored.get('latest')
    return {
        'enabled': True,
        'current': current,
        'latest': latest,
        'update_available': bool(latest) and is_newer(latest, current),
        'release_url': stored.get('release_url') or '',
    }
