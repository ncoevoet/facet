"""Literal rule groups, including authorized HTTP scope and legacy tag storage."""

from tests.shared_asset_helpers import shared_photo_paths
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.agent.tools_read import SearchFilters
from api import create_app
from api.agent.ui_tools import UiFilterPatch
from api.models.gallery import GalleryParams
from api.routers.gallery import _build_gallery_where
from db import DEFAULT_DB_PATH
from tag_query import tag_query_groups
# Explicit re-exports register the reused pytest fixtures in this test module.
from tests.test_person_match_groups import PREFIX, group as group, owner_client as owner_client
from tests.test_gallery_match_logic import _photo, library as library


def _matching(conn, groups, include_manual=True):
    clauses, values = _build_gallery_where({'tag_groups': json.dumps(groups, ensure_ascii=False)}, conn,
                                          include_manual=include_manual)
    return [row[0] for row in conn.execute('SELECT path FROM photos WHERE ' + ' AND '.join(clauses) + ' ORDER BY path', values)]


@pytest.mark.parametrize('raw', [
    'null', '[]', '{"any":true}', '{"other":["x"]}', '{"all":[""]}', '{"none":[1]}',
    '{"any":["first"],"any":["second"]}', '{"all":["line\\nbreak"]}',
    json.dumps({'any': ['x' * 201]}), json.dumps({'all': [str(i) for i in range(51)]}),
    '[' * 1500 + '0' + ']' * 1500,
])
def test_bad_group_refuses_in_all_api_and_agent_models(raw):
    for model in [GalleryParams, SearchFilters, UiFilterPatch]:
        with pytest.raises(ValidationError):
            model(tag_groups=raw)


def test_legacy_exact_tokens_and_manual_policy_without_wildcard_or_operator_parsing(library):
    conn = library
    _photo(conn, '/legacy.jpg', tags=' coast,\u2003ridge ,say "OR" %_\\,夜景 ')
    _photo(conn, '/substring.jpg', tags='coastline, ridgeway')
    _photo(conn, '/manual.jpg')
    conn.execute("INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES ('/manual.jpg', '夜景', 'user')")
    assert _matching(conn, {'all': ['coast', 'ridge']}) == ['/legacy.jpg']
    assert _matching(conn, {'any': ['coast, ridge']}) == []
    assert _matching(conn, {'any': ['say "OR" %_\\']}) == ['/legacy.jpg']
    assert _matching(conn, {'any': ['夜景']}) == ['/legacy.jpg', '/manual.jpg']
    assert _matching(conn, {'any': ['夜景']}, include_manual=False) == ['/legacy.jpg']
    assert _matching(conn, {'none': ['夜景']}) == ['/substring.jpg']


def test_valid_unicode_and_duplicate_names_preserve_literal_data():
    raw = json.dumps({'any': ['a,b', '"OR"', '夜景', 'e\u0301', '😀' * 200, 'a,b']}, ensure_ascii=False)
    groups = tag_query_groups(raw)
    assert groups['any'] == ['a,b', '"OR"', '夜景', 'e\u0301', '😀' * 200]
    assert tag_query_groups(GalleryParams(tag_groups=raw).tag_groups) == groups


@pytest.fixture()
def tagged(group, monkeypatch):
    monkeypatch.setattr('api.db_helpers._photo_tags_available', None)
    monkeypatch.setattr('api.config._photo_tags_available', None)
    monkeypatch.setattr('api.config._photo_tags_checked_at', 0)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        for name in ['alice/one.jpg', 'alice/two.jpg', 'bob/foreign.jpg']:
            conn.execute('INSERT INTO photo_tags(photo_path,tag) VALUES (?, ?)', (PREFIX + name, 'coast, ridge'))
        conn.execute('INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES (?, ?, ?)',
                     (PREFIX + 'alice/both.jpg', '夜景', 'user'))
    yield group
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM photo_tags WHERE photo_path LIKE ?', (PREFIX + '%',))
        conn.execute('DELETE FROM photo_manual_tags WHERE photo_path LIKE ?', (PREFIX + '%',))


def test_literal_groups_share_read_count_paths_and_excluded_write_scope(owner_client, tagged):
    query = json.dumps({'any': ['coast, ridge', '夜景'], 'none': ['absent']}, ensure_ascii=False)
    filters = {'tag_groups': query, 'path_prefix': PREFIX, 'type': '', 'hide_bursts': '0'}
    expected = {PREFIX + 'alice/' + name for name in ['one.jpg', 'two.jpg', 'both.jpg']}
    listed = owner_client.get('/api/photos', params=filters)
    assert listed.status_code == 200, listed.text
    assert {row['path'] for row in listed.json()['photos']} == expected
    assert owner_client.get('/api/photos/count', params=filters).json()['total'] == 3
    assert set(owner_client.get('/api/photos/paths', params=filters).json()['paths']) == expected
    rows = owner_client.post('/api/photos/by_paths', json={'paths': [r['path'] for r in tagged], 'filters': filters})
    assert rows.status_code == 200, rows.text
    assert {row['path'] for row in rows.json()['photos']} == expected
    edited = owner_client.post('/api/photos/batch_rating', json={'filters': filters, 'exclude': [PREFIX + 'alice/one.jpg'], 'rating': 3})
    assert edited.status_code == 200, edited.text
    assert edited.json()['count'] == 2
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        values = dict(conn.execute('SELECT photo_path, star_rating FROM user_preferences WHERE photo_path LIKE ?', (PREFIX + '%',)))
    assert values == {PREFIX + 'alice/two.jpg': 3, PREFIX + 'alice/both.jpg': 3}


def test_invalid_group_refuses_before_any_filtered_write(owner_client, tagged):
    result = owner_client.post('/api/photos/batch_rating', json={'filters': {'tag_groups': '{"any":false}'}, 'rating': 5})
    assert result.status_code == 422, result.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM user_preferences WHERE photo_path LIKE ?', (PREFIX + '%',)).fetchone()[0] == 0


def test_saved_owner_groups_keep_manual_membership_but_shared_response_hides_manual_tags(owner_client, tagged):
    query = json.dumps({'any': ['coast, ridge', '夜景']}, ensure_ascii=False)
    created = owner_client.post('/api/albums', json={
        'name': 'literal-tag-groups', 'is_smart': True,
        'smart_filter_json': json.dumps({'tag_groups': query}),
    })
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        expected = {PREFIX + 'alice/' + name for name in ['one.jpg', 'two.jpg', 'both.jpg']}
        opened = owner_client.get(f'/api/albums/{album}/photos')
        assert opened.status_code == 200, opened.text
        assert {photo['path'] for photo in opened.json()['photos']} == expected
        shared = owner_client.post(f'/api/albums/{album}/share')
        assert shared.status_code == 200, shared.text
        viewed = TestClient(create_app()).get(f'/api/shared/album/{album}', params={'token': shared.json()['share_token']})
        assert viewed.status_code == 200, viewed.text
        assert set(shared_photo_paths(viewed.json()['photos'])) == expected
        assert all(not photo.get('manual_tags') for photo in viewed.json()['photos'])
    finally:
        owner_client.delete(f'/api/albums/{album}')


def test_recipient_supplied_groups_cannot_probe_manual_tags(owner_client, tagged):
    created = owner_client.post('/api/albums', json={'name': 'manual-tag-sharing', 'is_smart': False})
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        result = owner_client.post(f'/api/albums/{album}/photos', json={
            'photo_paths': [row['path'] for row in tagged if '/alice/' in row['path']],
        })
        assert result.status_code == 200, result.text
        # A membership can outlive a directory permission. Sharing must retain
        # the owner's current visibility in both photos and facet metadata.
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('INSERT INTO album_photos(album_id,photo_path) VALUES (?,?)', (album, PREFIX + 'bob/foreign.jpg'))
            conn.execute('UPDATE photos SET camera_model=? WHERE path=?', ('Foreign private camera', PREFIX + 'bob/foreign.jpg'))
            conn.execute('INSERT INTO photo_tags(photo_path,tag) VALUES (?,?)', (PREFIX + 'bob/foreign.jpg', 'foreign-private-tag'))
        shared = owner_client.post(f'/api/albums/{album}/share')
        recipient = TestClient(create_app())
        baseline = recipient.get(f'/api/shared/album/{album}', params={'token': shared.json()['share_token']})
        assert baseline.status_code == 200, baseline.text
        assert set(shared_photo_paths(baseline.json()['photos'])) == {
            row['path'] for row in tagged if '/alice/' in row['path']
        }
        options = baseline.json()['filter_options']
        assert all(option['value'] != 'Foreign private camera' for option in options['cameras'])
        assert all(option['value'] != 'foreign-private-tag' for option in options['tags'])
        params = {'token': shared.json()['share_token'], 'tag_groups': json.dumps({'any': ['夜景']}, ensure_ascii=False)}
        manual = recipient.get(f'/api/shared/album/{album}', params=params)
        assert manual.status_code == 200, manual.text
        assert manual.json()['total'] == 0
        literal = recipient.get(f'/api/shared/album/{album}', params={
            **params, 'tag_groups': json.dumps({'any': ['coast, ridge']}),
        })
        assert literal.status_code == 200, literal.text
        assert set(shared_photo_paths(literal.json()['photos'])) == {
            PREFIX + 'alice/one.jpg', PREFIX + 'alice/two.jpg',
        }
    finally:
        owner_client.delete(f'/api/albums/{album}')


def test_agent_saved_rules_keep_literal_json_and_refuse_malformed_groups():
    from api.agent.album_filters import to_stored
    raw = '{"any":["a,b","夜景"],"none":["\\\"OR\\\""]}'
    error, saved = to_stored({'tag_groups': raw})
    assert error is None
    assert json.loads(saved['tag_groups']) == json.loads(raw)
    assert to_stored({'tag_groups': '{}'}) == (None, {})
    assert to_stored({'tag_groups': '{"none":true}'})[0] is not None


@pytest.mark.parametrize('raw', [None, False])
def test_invalid_saved_group_never_disappears_during_album_normalization(library, raw):
    from api.routers.albums import _normalize_smart_filters
    _photo(library, '/must-not-match.jpg', tags='anything')
    clauses, values = _build_gallery_where(_normalize_smart_filters({'tag_groups': raw}), library)
    assert library.execute('SELECT COUNT(*) FROM photos WHERE ' + ' AND '.join(clauses or ['1=1']), values).fetchone()[0] == 0
