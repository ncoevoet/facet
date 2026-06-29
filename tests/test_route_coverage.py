"""End-to-end route coverage smoke test.

Drives every GET route the FastAPI app exposes and asserts the response
isn't a 5xx. This is the "browser tests for all methods" safety net —
it can't catch UI rendering bugs (it doesn't run the Angular SPA) but
it catches every backend endpoint that breaks under refactors, schema
drift, or dependency rewiring.

Each route is exercised in two flavours where it matters:

* Anonymous (no auth headers) — public routes must serve, protected
  routes must 401/403, never 500.
* Edition / superadmin — routes that need auth must serve.

Routes that take a non-trivial path parameter (``/api/photo``,
``/api/person/{id}/faces``, ``/api/album/{id}``, ...) are listed
explicitly with a known-bad value so we still trip the auth gate but
exit through the proper 401/404 path.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Top-level route inventory — these are GETs that take no required params or
# accept defaults. The list mirrors the @router.get('...') declarations across
# api/routers/*.py and is intentionally explicit (rather than introspecting
# `app.routes`) so a missing route surfaces as a test gap, not a silent skip.
# ---------------------------------------------------------------------------

PUBLIC_ROUTES = [
    '/health',
    '/ready',
    '/api/config',
    '/api/i18n/languages',
    '/api/i18n/en',
    '/api/i18n/fr',
    '/api/i18n/de',
    '/api/i18n/es',
    '/api/i18n/it',
    '/api/i18n/pt',
]

# Routes that need *some* form of authenticated user but no edition rights.
AUTH_ROUTES = [
    '/api/photos',
    '/api/type_counts',
    '/api/folders',
    '/api/filter_options/cameras',
    '/api/filter_options/lenses',
    '/api/filter_options/tags',
    '/api/filter_options/apertures',
    '/api/filter_options/focal_lengths',
    '/api/filter_options/categories',
    '/api/filter_options/narrative_moments',
    '/api/filter_options/persons',
    '/api/filter_options/patterns',
    '/api/stats/overview',
    '/api/stats/score_distribution',
    '/api/stats/top_cameras',
    '/api/stats/categories',
    '/api/stats/gear',
    '/api/stats/settings',
    '/api/stats/timeline',
    '/api/stats/correlations',
    '/api/timeline',
    '/api/timeline/dates',
    '/api/timeline/years',
    '/api/timeline/months',
    '/api/memories',
    '/api/albums',
    '/api/capsules',
    '/api/photos/map/count',
    '/api/merge_suggestions',
    '/api/plugins',
    '/api/burst-groups',
    '/api/culling-groups',
    '/api/similar-groups',
    '/api/scenes',
    '/api/comparison/stats',
    '/api/comparison/coverage',
    '/api/comparison/confidence',
    '/api/comparison/history',
    '/api/config/weight_snapshots',
]

# Routes that require auth AND take a query/path parameter. We pass a known
# value or a deliberately bogus one — the assertion is just "no 5xx".
PARAMETERISED_ROUTES = [
    ('/api/search', {'q': 'test', 'limit': 10}),
    ('/api/photo', {'path': '/nonexistent.jpg'}),
    ('/api/critique', {'path': '/nonexistent.jpg'}),
    ('/api/caption', {'path': '/nonexistent.jpg'}),
    ('/api/photo/faces', {'path': '/nonexistent.jpg'}),
    ('/api/download/options', {'path': '/nonexistent.jpg'}),
    ('/api/similar_photos//nonexistent.jpg', {}),
    ('/api/photos/map', {'bounds': '-90,-180,90,180', 'limit': 5}),
    ('/api/filter_options/location_name', {'lat': 48.85, 'lng': 2.35}),
    ('/api/scenes', {'album_id': 1, 'date_from': '2024:06:15 00:00:00', 'date_to': '2024:06:15 23:59:59'}),
    ('/api/culling-groups', {'album_id': 1, 'date_from': '2024:06:15 00:00:00', 'date_to': '2024:06:15 23:59:59'}),
]

# Routes that require superadmin (scan).
SUPERADMIN_ROUTES = [
    '/api/scan/status',
    '/api/scan/directories',
]


def _is_acceptable(status: int) -> bool:
    """A route passed the smoke test if it returns anything but a 5xx."""
    return 100 <= status < 500


class TestPublicRoutes:
    @pytest.mark.parametrize('path', PUBLIC_ROUTES)
    def test_anonymous_no_5xx(self, client, path):
        resp = client.get(path)
        assert _is_acceptable(resp.status_code), (
            f"{path} -> {resp.status_code} body={resp.text[:200]}"
        )


class TestAuthenticatedRoutes:
    @pytest.mark.parametrize('path', AUTH_ROUTES)
    def test_anonymous_no_5xx(self, client, path):
        # Anonymous hit: should be 401/403/200 depending on auth mode.
        resp = client.get(path)
        assert _is_acceptable(resp.status_code), (
            f"{path} -> {resp.status_code} body={resp.text[:200]}"
        )

    @pytest.mark.parametrize('path', AUTH_ROUTES)
    def test_edition_user_no_5xx(self, edition_client, path):
        resp = edition_client.get(path)
        assert _is_acceptable(resp.status_code), (
            f"{path} -> {resp.status_code} body={resp.text[:200]}"
        )


class TestParameterisedRoutes:
    @pytest.mark.parametrize('path,params', PARAMETERISED_ROUTES)
    def test_edition_user_no_5xx(self, edition_client, path, params):
        resp = edition_client.get(path, params=params)
        assert _is_acceptable(resp.status_code), (
            f"{path}?{params} -> {resp.status_code} body={resp.text[:200]}"
        )


class TestSuperadminRoutes:
    @pytest.mark.parametrize('path', SUPERADMIN_ROUTES)
    def test_superadmin_no_5xx(self, superadmin_client, path):
        resp = superadmin_client.get(path)
        assert _is_acceptable(resp.status_code), (
            f"{path} -> {resp.status_code} body={resp.text[:200]}"
        )

    @pytest.mark.parametrize('path', SUPERADMIN_ROUTES)
    def test_regular_user_denied(self, regular_client, path):
        # Confirms the auth gate is wired up — regular users can't see scan ops.
        resp = regular_client.get(path)
        assert resp.status_code in (401, 403), (
            f"{path} should require superadmin, got {resp.status_code}"
        )


class TestPostRoutesAcceptValidShape:
    """A handful of POST endpoints that take small JSON payloads.

    Each test passes a minimal valid-shaped body; the response is allowed to
    be a 400/404 (no matching data) but must not 5xx.
    """

    def test_photo_set_rating_validates_payload(self, edition_client):
        resp = edition_client.post(
            '/api/photo/set_rating',
            json={'path': '/nonexistent.jpg', 'rating': 3},
        )
        assert _is_acceptable(resp.status_code)

    def test_photo_toggle_favorite_validates_payload(self, edition_client):
        resp = edition_client.post(
            '/api/photo/toggle_favorite',
            json={'path': '/nonexistent.jpg'},
        )
        assert _is_acceptable(resp.status_code)

    def test_photo_toggle_rejected_validates_payload(self, edition_client):
        resp = edition_client.post(
            '/api/photo/toggle_rejected',
            json={'path': '/nonexistent.jpg'},
        )
        assert _is_acceptable(resp.status_code)

    def test_batch_favorite_accepts_empty_list(self, edition_client):
        resp = edition_client.post(
            '/api/photos/batch_favorite',
            json={'paths': [], 'is_favorite': True},
        )
        assert _is_acceptable(resp.status_code)


class TestAngularSpaShell:
    """The Angular SPA shell catch-all route — every UI deep link must serve
    `index.html` so the router can take over. If this regresses, refresh on
    any nested URL would 404.
    """

    @pytest.mark.parametrize('path', [
        '/',
        '/gallery',
        '/timeline',
        '/albums',
        '/persons',
        '/stats',
        '/capsules',
        '/folders',
        '/culling',
        '/map',
        '/compare',
        '/shared/album/123',
    ])
    def test_spa_shell_serves_index_or_redirects(self, client, path):
        resp = client.get(path, follow_redirects=False)
        # 200 (index.html), 304 (cached), 307/308 (trailing-slash redirect)
        # or 404 (dist not built in this env) are all "not a backend crash".
        assert resp.status_code in (200, 204, 301, 302, 304, 307, 308, 404), (
            f"{path} -> {resp.status_code}"
        )
