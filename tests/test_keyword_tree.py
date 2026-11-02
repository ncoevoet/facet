"""Authorized hierarchy discovery and branch query semantics on real catalog rows."""

import sqlite3
import json
from pathlib import Path
from uuid import uuid4

import pytest

from api import config
from db import DEFAULT_DB_PATH
from db.keyword_hierarchy import assign_node, assign_path, ensure_path


@pytest.fixture
def hierarchy(tmp_path, seed_photos_prefix, monkeypatch):
    paths = [tmp_path / 'public' / f'{i}.jpg' for i in range(3)] + [tmp_path / 'private' / 'secret.jpg']
    seed_photos_prefix(str(tmp_path) + '/', [{'path': str(path), 'filename': path.name, 'tags': 'animals/cat'} for path in paths])
    paths = list(map(str, paths))
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        owner: {'directories': [str(Path(paths[0]).parent)]} for owner in ('test', 'u1')})
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        domestic, _ = assign_path(conn, paths[0], ['Animals', 'Domestic', 'Cat'])
        wild, _ = assign_path(conn, paths[1], ['Animals', 'Wild', 'Cat'])
        root = ensure_path(conn, ['Animals'])
        assign_node(conn, paths[0], root)  # Same photo in parent and leaf must count once in branch.
        assign_node(conn, paths[3], domestic)
        hidden, _ = assign_path(conn, paths[3], ['Private-' + tmp_path.name, 'Alice'])
        ensure_path(conn, ['Unused vocabulary'])
        conn.execute("UPDATE keyword_nodes SET name_key='invalid-private' WHERE id=?", (hidden,))
    try:
        yield paths, root, domestic, wild
    finally:
        # The shared fixture DB retains unused vocabulary after photo cleanup.
        # Restore our deliberately malformed private definition for later tests.
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute("UPDATE keyword_nodes SET name_key='alice' WHERE id=?", (hidden,))


def test_tree_returns_only_visible_assignments_and_ancestors_with_distinct_branch_counts(regular_client, hierarchy):
    paths, root, domestic, wild = hierarchy
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        before = list(conn.iterdump())
    response = regular_client.get('/api/manual_tags/hierarchy')
    assert response.status_code == 200, response.text
    assert response.headers['Cache-Control'] == 'no-store'
    nodes = response.json()['nodes']
    assert {tuple(node['segments']) for node in nodes} == {
        ('Animals',), ('Animals', 'Domestic'), ('Animals', 'Domestic', 'Cat'),
        ('Animals', 'Wild'), ('Animals', 'Wild', 'Cat')}
    by_id = {node['id']: node for node in nodes}
    assert (by_id[root]['direct_count'], by_id[root]['branch_count']) == (1, 2)
    assert (by_id[domestic]['direct_count'], by_id[domestic]['branch_count']) == (1, 1)
    assert by_id[wild]['branch_count'] == 1
    assert 'Private' not in response.text and 'Unused vocabulary' not in response.text
    assert not any(path in response.text for path in paths)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert list(conn.iterdump()) == before


def test_branch_query_matches_descendant_assignments_not_literal_flat_tags_and_never_hidden_photos(regular_client, hierarchy):
    paths, root, domestic, _ = hierarchy
    def results(node):
        response = regular_client.get('/api/photos', params={'keyword_branch': node, 'per_page': 200})
        assert response.status_code == 200, response.text
        return {photo['path'] for photo in response.json()['photos']}
    assert results(root) == set(paths[:2])
    assert results(domestic) == {paths[0]}
    assert results(str(uuid4())) == set()
    assert regular_client.get('/api/photos', params={'keyword_branch': 'not-an-identity'}).status_code == 422


def test_private_hierarchy_filters_fail_closed_in_shared_request_projection(hierarchy):
    from api.routers.gallery import _apply_text_filters
    _, root, _, _ = hierarchy
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        clauses, values = [], []
        _apply_text_filters(clauses, values, {'keyword_branch': root}, conn, include_manual=False)
        assert '0=1' in clauses
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE ' + ' AND '.join(clauses), values).fetchone()[0] == 0


def test_filtered_batch_uses_the_same_explicit_branch_membership(edition_client, hierarchy):
    paths, root, _, _ = hierarchy
    response = edition_client.post('/api/photos/batch_rating', json={'filters': {'keyword_branch': root}, 'rating': 3})
    assert response.status_code == 200, response.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        ratings = dict(conn.execute('SELECT photo_path,star_rating FROM user_preferences WHERE user_id=? AND photo_path LIKE ?',
                                    ('test', str(Path(paths[0]).parents[1]) + '/%')))
        assert ratings == {paths[0]: 3, paths[1]: 3}


def test_saved_branch_membership_works_for_owner_and_shared_album_without_exposing_rule(edition_client, hierarchy):
    from fastapi.testclient import TestClient
    from api import create_app
    paths, root, _, _ = hierarchy
    created = edition_client.post('/api/albums', json={'name': 'hierarchy fixture', 'is_smart': True,
        'smart_filter_json': json.dumps({'keyword_branch': root})})
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        opened = edition_client.get(f'/api/albums/{album}/photos')
        assert opened.status_code == 200, opened.text
        assert {photo['path'] for photo in opened.json()['photos']} == set(paths[:2])
        shared = edition_client.post(f'/api/albums/{album}/share')
        assert shared.status_code == 200, shared.text
        viewed = TestClient(create_app()).get(f'/api/shared/album/{album}', params={'token': shared.json()['share_token']})
        assert viewed.status_code == 200, viewed.text
        assert {photo['path'] for photo in viewed.json()['photos']} == set(paths[:2])
        assert 'smart_filter_json' not in viewed.json()['album']
    finally:
        edition_client.delete(f'/api/albums/{album}')


@pytest.mark.parametrize('malformed', [False, None, 0, [], {}])
def test_malformed_saved_branch_never_broadens_owner_or_shared_membership(edition_client, hierarchy, malformed):
    from fastapi.testclient import TestClient
    from api import create_app
    created = edition_client.post('/api/albums', json={'name': 'invalid branch fixture', 'is_smart': True,
        'smart_filter_json': json.dumps({'keyword_branch': malformed})})
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        opened = edition_client.get(f'/api/albums/{album}/photos')
        assert opened.status_code == 200 and opened.json()['photos'] == [], opened.text
        shared = edition_client.post(f'/api/albums/{album}/share')
        assert shared.status_code == 200, shared.text
        viewed = TestClient(create_app()).get(f'/api/shared/album/{album}', params={'token': shared.json()['share_token']})
        assert viewed.status_code == 200 and viewed.json()['photos'] == [], viewed.text
    finally:
        edition_client.delete(f'/api/albums/{album}')


def test_tree_released_schema_read_never_initializes_tables():
    from api.keyword_tree import keyword_tree
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY)')
        before = list(conn.iterdump())
        conn.execute('PRAGMA query_only=ON')
        assert keyword_tree(conn, None) == {'nodes': []}
        assert list(conn.iterdump()) == before


def test_branch_membership_is_materialized_once_instead_of_correlated_per_photo(hierarchy):
    from api.routers.gallery import _apply_text_filters
    _, root, _, _ = hierarchy
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        clauses, values = [], []
        _apply_text_filters(clauses, values, {'keyword_branch': root}, conn)
        sql = 'SELECT COUNT(*) FROM photos WHERE ' + ' AND '.join(clauses)
        assert conn.execute(sql, values).fetchone()[0] == 3  # Including private photo before caller's visibility clause.
        plan = [row[3] for row in conn.execute('EXPLAIN QUERY PLAN ' + sql, values)]
        assert not any('CORRELATED' in detail for detail in plan), plan
