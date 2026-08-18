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

import json
import sqlite3

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


# ---------------------------------------------------------------------------
# The two endpoints that own a PRIVATE cache branch.
#
# ``_cached_filter_query`` was fixed to consult ``vis``, but ``tags`` and
# ``colors`` do not use it — each re-implements the cache-then-query dance
# inline and gated it on ``is_multi_user_enabled()`` alone. A single-user
# install with a viewer password resolves ``vis`` to ``' AND 0=1'`` while
# ``is_multi_user_enabled()`` stays False, so both kept serving (and, for
# colours, kept WRITING) the whole-library payload.
# ---------------------------------------------------------------------------

SECRET_TAGS = [['SECRET-TAG', 7]]
SECRET_COLORS = [['warm', 99]]


def test_tags_cache_hit_is_bypassed_when_visibility_restricts(monkeypatch, anonymous_client):
    """The tag list is the private-cache twin of the cameras leak."""
    _force_fresh_cache(monkeypatch, SECRET_TAGS)
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('0=1', []))

    resp = anonymous_client.get('/api/filter_options/tags')

    assert resp.status_code == 200
    assert resp.json()['tags'] == [], (
        "cached whole-library tag list leaked past the visibility clause"
    )


def test_tags_cache_is_still_used_on_an_open_install(monkeypatch, anonymous_client):
    """The bypass must not cost an open install its tag cache."""
    _force_fresh_cache(monkeypatch, SECRET_TAGS)
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('1=1', []))

    resp = anonymous_client.get('/api/filter_options/tags')

    assert resp.status_code == 200
    assert resp.json() == {'tags': SECRET_TAGS, 'cached': True}


def test_colors_cache_hit_is_bypassed_when_visibility_restricts(monkeypatch, anonymous_client):
    """Colour facets are cached under two private keys; both must be skipped."""
    _force_fresh_cache(monkeypatch, SECRET_COLORS)
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('0=1', []))

    resp = anonymous_client.get('/api/filter_options/colors')

    assert resp.status_code == 200
    body = resp.json()
    assert body['temps'] == [], "cached whole-library colour temps leaked"
    assert body['hue_buckets'] == [], "cached whole-library hue buckets leaked"


def test_colors_cache_is_still_used_on_an_open_install(monkeypatch, anonymous_client):
    """The bypass must not cost an open install its colour cache."""
    _force_fresh_cache(monkeypatch, SECRET_COLORS)
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('1=1', []))

    resp = anonymous_client.get('/api/filter_options/colors')

    assert resp.status_code == 200
    assert resp.json() == {
        'temps': SECRET_COLORS, 'hue_buckets': SECRET_COLORS, 'cached': True,
    }


COLOR_CACHE_KEYS = ('color_temps', 'color_hue_buckets')
COLORS_PREFIX = '/filteropt-colors/'


def _read_color_cache():
    conn = sqlite3.connect(db_module.DEFAULT_DB_PATH)
    try:
        return {
            key: conn.execute(
                "SELECT value FROM stats_cache WHERE key = ?", (key,)
            ).fetchone()
            for key in COLOR_CACHE_KEYS
        }
    finally:
        conn.close()


def _clear_color_cache():
    conn = sqlite3.connect(db_module.DEFAULT_DB_PATH)
    try:
        for key in COLOR_CACHE_KEYS:
            conn.execute("DELETE FROM stats_cache WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()


def test_colors_cache_is_not_poisoned_by_a_restricted_caller(
    monkeypatch, anonymous_client, seed_photos_prefix
):
    """A cache MISS is the second half of the same bug.

    The restricted caller computes the facets under ``AND 0=1``, gets nothing,
    and the old ``use_cache`` flag then persisted those empty lists into the
    whole-library ``stats_cache`` row — blanking the real user's colour filter
    for the full 300s TTL.
    """
    seed_photos_prefix(COLORS_PREFIX, [
        {'path': COLORS_PREFIX + 'warm.jpg', 'filename': 'warm.jpg',
         'color_temp': 'warm', 'dominant_hue': 20.0},
    ])
    monkeypatch.setattr(db_module, 'get_cached_stat', lambda *a, **k: (None, False))
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('0=1', []))
    _clear_color_cache()

    try:
        resp = anonymous_client.get('/api/filter_options/colors')

        assert resp.status_code == 200
        assert resp.json()['temps'] == []
        assert _read_color_cache() == {key: None for key in COLOR_CACHE_KEYS}, (
            "the restricted caller's empty result was written into the "
            "whole-library colour cache"
        )
    finally:
        _clear_color_cache()


def test_colors_cache_is_written_on_an_open_install(
    monkeypatch, anonymous_client, seed_photos_prefix
):
    """The write path must survive: an unrestricted miss still populates the cache."""
    seed_photos_prefix(COLORS_PREFIX, [
        {'path': COLORS_PREFIX + 'warm.jpg', 'filename': 'warm.jpg',
         'color_temp': 'warm', 'dominant_hue': 20.0},
    ])
    monkeypatch.setattr(db_module, 'get_cached_stat', lambda *a, **k: (None, False))
    monkeypatch.setattr(filter_options, 'get_visibility_clause', lambda user_id: ('1=1', []))
    _clear_color_cache()

    try:
        resp = anonymous_client.get('/api/filter_options/colors')

        assert resp.status_code == 200
        assert ['warm', 1] in resp.json()['temps']
        cached = _read_color_cache()
        assert cached['color_temps'] is not None, "open install lost its colour cache write"
        assert json.loads(cached['color_temps'][0]) == [['warm', 1]]
    finally:
        _clear_color_cache()
