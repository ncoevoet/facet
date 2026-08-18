"""Regression tests for the filter-options visibility short-circuit (A6 #1).

The bug: ``api.routers.filter_options._vis_where`` returned ``('', [])`` for an
anonymous request *without ever calling* ``get_visibility_clause``. On a locked
or multi-user install ``get_visibility_clause(None)`` returns a fail-closed
``0=1`` clause, so short-circuiting before that call served whole-library
metadata (cameras, lenses, tags, persons, categories, …) to anonymous callers.

The fix must ALWAYS resolve the clause first, exactly like ``stats._vis_where``.

These tests monkeypatch ``get_visibility_clause`` (a DB helper), never the auth
dependencies — per the repo LAW, auth is swapped via the shared conftest
``anonymous_client`` fixture / ``app.dependency_overrides`` only.
"""

from api.routers import filter_options


def test_vis_where_calls_visibility_clause_for_anonymous(monkeypatch):
    """Anonymous (user=None) must still consult get_visibility_clause.

    This is the core regression guard: the old short-circuit returned before
    the call, so the spy would record nothing.
    """
    seen = []

    def spy(user_id):
        seen.append(user_id)
        return '1=1', []

    monkeypatch.setattr(filter_options, 'get_visibility_clause', spy)

    filter_options._vis_where(None)

    assert seen == [None], "get_visibility_clause must be called with None for anon"


def test_vis_where_fails_closed_on_locked_install(monkeypatch):
    """When the clause denies anon (0=1) the fragment must carry it through."""
    monkeypatch.setattr(
        filter_options, 'get_visibility_clause', lambda user_id: ('0=1', [])
    )

    frag, params = filter_options._vis_where(None)

    assert frag == ' AND 0=1'
    assert params == []


def test_vis_where_open_install_returns_empty(monkeypatch):
    """On a fully open install (1=1) the fragment collapses to empty."""
    monkeypatch.setattr(
        filter_options, 'get_visibility_clause', lambda user_id: ('1=1', [])
    )

    assert filter_options._vis_where(None) == ('', [])


def test_vis_where_passes_authenticated_user_id(monkeypatch):
    """An authenticated user forwards its user_id and the returned params."""
    seen = []

    def spy(user_id):
        seen.append(user_id)
        return 'path LIKE ?', ['/u/alice/%']

    monkeypatch.setattr(filter_options, 'get_visibility_clause', spy)

    class _U:
        user_id = 'alice'

    frag, params = filter_options._vis_where(_U())

    assert seen == ['alice']
    assert frag == ' AND path LIKE ?'
    assert params == ['/u/alice/%']


def test_filter_options_cameras_anonymous_hits_visibility_clause(
    anonymous_client, monkeypatch
):
    """End-to-end via the shared anonymous_client fixture.

    Proves the endpoint path resolves visibility for the anonymous (None) user
    rather than short-circuiting. The spy forces a fail-closed clause so the
    response is empty even if the library holds cameras.
    """
    seen = []

    def spy(user_id):
        seen.append(user_id)
        return '0=1', []

    monkeypatch.setattr(filter_options, 'get_visibility_clause', spy)

    resp = anonymous_client.get('/api/filter_options/cameras')

    assert resp.status_code == 200
    assert None in seen, "anon endpoint must resolve visibility for user_id=None"
    assert resp.json()['cameras'] == []


# ---------------------------------------------------------------------------
# The cache short-circuit.
#
# Resolving the clause is not the same as applying it. ``_vis_where`` is
# correct now, but ``_cached_filter_query`` returned the cached payload BEFORE
# running the query the clause lives in, so a restricted caller still got the
# whole-library answer. The tests above cannot catch that: nothing populates
# the stats cache during a test run, so the cache branch is never taken and
# they pass without ever exercising it. These force the cache hit.
# ---------------------------------------------------------------------------

import db as db_module  # noqa: E402

LEAKED = [['SECRET CAMERA', 42]]


def _force_fresh_cache(monkeypatch, payload=LEAKED):
    """Make every cache lookup a hit, as `database.py --refresh-stats` would."""
    monkeypatch.setattr(db_module, 'get_cached_stat', lambda *a, **k: (payload, True))


def test_cache_hit_is_bypassed_when_visibility_restricts(monkeypatch, anonymous_client):
    """A restricted caller must not be served the library-wide cached payload."""
    _force_fresh_cache(monkeypatch)
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('0=1', []))

    resp = anonymous_client.get('/api/filter_options/cameras')

    assert resp.status_code == 200
    assert resp.json()['cameras'] == [], "cached whole-library payload leaked past the visibility clause"


def test_cache_hit_is_bypassed_for_person_names(monkeypatch, anonymous_client):
    """Person names are the most sensitive thing these dropdowns carry."""
    _force_fresh_cache(monkeypatch, [[1, 'Alice', 12]])
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('0=1', []))

    resp = anonymous_client.get('/api/filter_options/persons')

    assert resp.status_code == 200
    assert resp.json()['persons'] == [], "cached person names leaked to a restricted caller"


def test_cache_is_still_used_on_an_open_install(monkeypatch, anonymous_client):
    """The bypass must not cost every open install its cache."""
    _force_fresh_cache(monkeypatch)
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('1=1', []))

    resp = anonymous_client.get('/api/filter_options/cameras')

    assert resp.status_code == 200
    assert resp.json() == {'cameras': LEAKED, 'cached': True}
