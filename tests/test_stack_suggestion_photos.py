"""Suggestion enrichment preserves detector order, visibility and caller marks."""
from contextlib import contextmanager
import sqlite3

import pytest

from api.database import get_db


def _seed(seed_photos_prefix):
    # Detector order (lead, then aggregate) deliberately conflicts with score order.
    rows = [dict(path=f'/suggestion-photos/{n}.jpg', filename=f'{n}.jpg',
                 duplicate_group_id=930001, is_duplicate_lead=int(n == 1),
                 burst_group_id=930002, is_burst_lead=int(n == 0),
                 aggregate=9.0 - n, aesthetic=2.0 + n, tech_sharpness=3.0,
                 is_blink=0, date_taken='2026:10:29 09:00:00',
                 eyes_open_score=8.0, expression_score=7.0,
                 is_kept=1, is_rejected=0, is_favorite=1, star_rating=4,
                 preview_revision=f'revision-{n}') for n in range(3)]
    seed_photos_prefix('/suggestion-photos/', rows)
    return [r['path'] for r in rows]


def _request(client, **body):
    return client.post('/api/stacks/suggestions', json={
        'filters': {'path_prefix': '/suggestion-photos/'}, **body})


@pytest.mark.parametrize('include', [None, False])
def test_default_and_false_return_detector_id_without_photo_rows(edition_client, seed_photos_prefix, include):
    _seed(seed_photos_prefix)
    response = _request(edition_client, **({} if include is None else {'include_photos': include}))
    assert response.status_code == 200, response.text
    [group] = response.json()['suggestions']
    assert group['group_id'] == 930001
    assert group['photos'] is None


def test_photo_rows_follow_suggestion_order_and_include_exact_fields_without_writes(
        edition_client, seed_photos_prefix, monkeypatch):
    from api import config
    from api.routers import stacks as router

    paths = _seed(seed_photos_prefix)
    monkeypatch.setattr('api.db_helpers.is_multi_user_enabled', lambda: False)
    monkeypatch.setitem(config._FULL_CONFIG, 'burst_scoring', {'weight_aggregate': 1,
        'weight_aesthetic': 0, 'weight_sharpness': 0, 'weight_blink': 0})
    statements = []

    @contextmanager
    def traced_db():
        with get_db() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(router, 'get_db', traced_db)
    with get_db() as conn:
        before = list(conn.iterdump())
    response = _request(edition_client, include_photos=True)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    [group] = response.json()['suggestions']
    assert group['group_id'] == 930001
    assert group['paths'] == [paths[1], paths[0], paths[2]]
    assert [p['path'] for p in group['photos']] == group['paths']
    assert [p['burst_score'] for p in group['photos']] == [8.0, 9.0, 7.0]
    assert group['photos'][0] == dict(path=paths[1], filename='1.jpg', aggregate=8.0,
        aesthetic=3.0, tech_sharpness=3.0, is_blink=0, is_burst_lead=0,
        date_taken='2026:10:29 09:00:00', burst_score=8.0,
        eyes_open_score=8.0, expression_score=7.0, is_rejected=0, is_kept=1,
        is_favorite=1, star_rating=4, preview_revision='revision-1')
    with get_db() as conn:
        assert list(conn.iterdump()) == before
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')) for sql in statements)


def test_enriched_bursts_keep_their_detector_id_and_order(edition_client, seed_photos_prefix):
    paths = _seed(seed_photos_prefix)
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET duplicate_group_id=NULL WHERE path LIKE '/suggestion-photos/%'")
    response = _request(edition_client, include_photos=True)
    assert response.status_code == 200, response.text
    [group] = response.json()['suggestions']
    assert group['kind'] == 'burst' and group['group_id'] == 930002
    assert group['paths'] == paths
    assert [p['path'] for p in group['photos']] == paths


def test_enriched_rows_use_each_accounts_marks_and_preserve_filter_scope(
        edition_client, regular_client, seed_photos_prefix, monkeypatch):
    from api import config

    paths = _seed(seed_photos_prefix)
    monkeypatch.setattr('api.db_helpers.is_multi_user_enabled', lambda: True)
    monkeypatch.setattr('api.routers.stacks.is_multi_user_enabled', lambda: True)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': ['/suggestion-photos/']},
        'u1': {'directories': ['/suggestion-photos/']}})
    with get_db() as conn, conn:
        conn.executemany('INSERT INTO user_preferences (user_id,photo_path,is_rejected,is_kept,is_favorite,star_rating) '
                         'VALUES (?,?,?,?,?,?)', [
            ('test', paths[0], 0, 1, 1, 5), ('u1', paths[0], 1, 0, 0, 2)])
    for client, expected in ((edition_client, [0, 1, 1, 5]), (regular_client, [1, 0, 0, 2])):
        response = _request(client, include_photos=True)
        assert response.status_code == 200, response.text
        [group] = response.json()['suggestions']
        photo = next(p for p in group['photos'] if p['path'] == paths[0])
        assert [photo[k] for k in ('is_rejected', 'is_kept', 'is_favorite', 'star_rating')] == expected
        filtered = _request(client, include_photos=True, filters={
            'path_prefix': '/suggestion-photos/', 'hide_rejected': True})
        assert filtered.status_code == 200, filtered.text
        [narrow] = filtered.json()['suggestions']
        wanted = [paths[1], paths[2]] if client is regular_client else [paths[1], paths[0], paths[2]]
        assert narrow['paths'] == wanted
        assert [p['path'] for p in narrow['photos']] == wanted


def test_enrichment_never_fetches_hidden_members(regular_client, seed_photos_prefix, monkeypatch):
    from api import config

    visible = ['/suggestion-scope/visible/a.jpg', '/suggestion-scope/visible/b.jpg']
    hidden = '/suggestion-scope/hidden/lead.jpg'
    seed_photos_prefix('/suggestion-scope/', [dict(path=p, filename=p.rsplit('/', 1)[-1],
        duplicate_group_id=930003, is_duplicate_lead=int(p == hidden)) for p in [*visible, hidden]])
    monkeypatch.setattr('api.db_helpers.is_multi_user_enabled', lambda: True)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'u1': {'directories': ['/suggestion-scope/visible/']}})
    response = regular_client.post('/api/stacks/suggestions', json={'include_photos': True,
        'filters': {'path_prefix': '/suggestion-scope/'}})
    assert response.status_code == 200, response.text
    [group] = response.json()['suggestions']
    assert group['paths'] == visible
    assert [p['path'] for p in group['photos']] == visible
    assert hidden not in response.text


def test_members_and_enrichment_share_the_read_snapshot(edition_client, seed_photos_prefix, monkeypatch):
    from db import stack_suggestions

    paths = _seed(seed_photos_prefix)
    original = stack_suggestions.suggestions

    def discover_then_commit(*args, **kwargs):
        result = original(*args, **kwargs)
        # A writer commits between candidate discovery and enrichment. WAL readers
        # must still see the original pixels/marks revision from their transaction.
        with get_db() as writer, writer:
            writer.execute('UPDATE photos SET aggregate=1,preview_revision=? WHERE path=?',
                           ('later-revision', paths[1]))
        return result

    monkeypatch.setattr(stack_suggestions, 'suggestions', discover_then_commit)
    response = _request(edition_client, include_photos=True)
    assert response.status_code == 200, response.text
    [group] = response.json()['suggestions']
    photo = group['photos'][0]
    assert photo['path'] == paths[1]
    assert photo['aggregate'] == 8.0 and photo['preview_revision'] == 'revision-1'
    with get_db() as conn:
        assert tuple(conn.execute('SELECT aggregate,preview_revision FROM photos WHERE path=?', (paths[1],)).fetchone()) == (1.0, 'later-revision')


def test_enrichment_chunks_bounded_members_without_losing_order(edition_client, seed_photos_prefix):
    seed_photos_prefix('/suggestion-photos/', [dict(path=f'/suggestion-photos/{g}-{n:04}.jpg',
        filename=f'{g}-{n:04}.jpg', duplicate_group_id=930010 + g)
        for g in range(3) for n in range(900)])
    response = _request(edition_client, include_photos=True)
    assert response.status_code == 200, response.text
    groups = response.json()['suggestions']
    assert [len(g['paths']) for g in groups] == [900, 900]
    for group in groups:
        assert [p['path'] for p in group['photos']] == group['paths']


@pytest.mark.skipif(not hasattr(sqlite3.Connection, 'setlimit'),
                    reason='Python 3.10 cannot lower the SQLite connection variable limit')
@pytest.mark.parametrize('case_insensitive', [True, False])
def test_enrichment_reserves_visibility_bindings_under_legacy_sqlite_limit(
        regular_client, seed_photos_prefix, monkeypatch, case_insensitive):
    from api import config, db_helpers
    from api.routers import stacks as router

    visible = [f'/suggestion-bind-budget/visible/{n:04}.jpg' for n in range(900)]
    hidden = '/suggestion-bind-budget/hidden/lead.jpg'
    seed_photos_prefix('/suggestion-bind-budget/', [dict(path=p,
        filename=p.rsplit('/', 1)[-1], duplicate_group_id=930020,
        is_duplicate_lead=int(p == hidden)) for p in [*visible, hidden]])
    monkeypatch.setattr(db_helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(db_helpers, '_CASE_INSENSITIVE_HOST', case_insensitive)
    monkeypatch.setattr(router, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'u1': {'directories': [
        '/suggestion-bind-budget/visible/',
        *[f'/suggestion-bind-budget/unrelated-{n}/' for n in range(99)]]}})
    assert len(db_helpers.get_visibility_clause('u1')[1]) == (100 if case_insensitive else 200)

    @contextmanager
    def bounded_db():
        with get_db() as conn:
            conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
            yield conn

    monkeypatch.setattr(router, 'get_db', bounded_db)
    body = {'filters': {'path_prefix': '/suggestion-bind-budget/'}}
    baseline = regular_client.post('/api/stacks/suggestions', json=body)
    assert baseline.status_code == 200, baseline.text
    [original] = baseline.json()['suggestions']
    assert original['paths'] == visible
    assert original['photos'] is None
    enriched = regular_client.post('/api/stacks/suggestions', json={**body, 'include_photos': True})
    assert enriched.status_code == 200, enriched.text
    [group] = enriched.json()['suggestions']
    assert group['paths'] == visible
    assert [p['path'] for p in group['photos']] == visible
    assert group['cover_path'] == visible[0]
    assert hidden not in enriched.text
