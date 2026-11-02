"""Personal zero stars is not a fallback to catalog/another user's rating."""

from tests.shared_asset_helpers import shared_photo_paths
import sqlite3
import json

import pytest

from db import DEFAULT_DB_PATH

PREFIX = '/personal-star-filter/'
VISIBLE = PREFIX + 'visible/'
PATHS = {name: VISIBLE + name + '.jpg' for name in ('absent', 'zero', 'imported', 'personal')}
HIDDEN = PREFIX + 'hidden/private.jpg'


@pytest.fixture
def ratings(seed_photos_prefix, monkeypatch):
    from api import db_helpers
    seed_photos_prefix(PREFIX, [
        {'path': PATHS['absent'], 'filename': 'absent.jpg', 'star_rating': 5},
        {'path': PATHS['zero'], 'filename': 'zero.jpg', 'star_rating': 4},
        {'path': PATHS['imported'], 'filename': 'imported.jpg', 'star_rating': 1},
        {'path': PATHS['personal'], 'filename': 'personal.jpg', 'star_rating': 0},
        {'path': HIDDEN, 'filename': 'private.jpg', 'star_rating': 0},
    ])
    monkeypatch.setattr(db_helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(db_helpers, 'get_user_directories', lambda owner: [VISIBLE])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.executemany('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,?)', [
            ('u1', PATHS['zero'], 2), ('u1', PATHS['imported'], 3), ('u1', PATHS['personal'], 4),
            ('other-user', PATHS['absent'], 5), ('other-user', PATHS['zero'], 5), ('u1', HIDDEN, 0),
        ])
        conn.execute('UPDATE user_preferences SET star_rating=0 WHERE user_id=? AND photo_path=?', ('u1', PATHS['zero']))
        conn.execute("UPDATE photo_metadata_edits SET source='xmp',source_at='2026-01-01T00:00:00Z',source_path='/private/import.xmp' "
                     "WHERE user_id='u1' AND photo_path=? AND field='star_rating'", (PATHS['imported'],))
    yield


def snapshot():
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        return [conn.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall()
                for table in ('photos', 'user_preferences', 'photo_metadata_edits')]


@pytest.mark.parametrize(('low', 'high', 'names'), [('0', '0', {'absent', 'zero'}), ('3', '4', {'imported', 'personal'})])
def test_personal_star_range_matches_list_count_and_explicit_targets(regular_client, ratings, low, high, names):
    params = {'path_prefix': VISIBLE, 'min_star_rating': low, 'max_star_rating': high,
              'hide_blinks': '0', 'hide_bursts': '0', 'hide_duplicates': '0',
              'hide_brackets': '0', 'hide_panoramas': '0', 'hide_rejected': '0', 'type': ''}
    before = snapshot()
    listed = regular_client.get('/api/photos', params=params)
    assert listed.status_code == 200, listed.text
    expected = {PATHS[name] for name in names}
    assert {photo['path'] for photo in listed.json()['photos']} == expected
    assert listed.json()['photo_total'] == len(expected)
    counted = regular_client.get('/api/photos/count', params=params)
    assert counted.status_code == 200, counted.text
    assert counted.json()['total'] == len(expected)
    paths = regular_client.get('/api/photos/paths', params=params)
    assert paths.status_code == 200, paths.text
    assert set(paths.json()['paths']) == expected
    explicit = regular_client.post('/api/photos/by_paths', json={'paths': [*PATHS.values(), HIDDEN], 'filters': params})
    assert explicit.status_code == 200, explicit.text
    assert {photo['path'] for photo in explicit.json()['photos']} == expected
    for name, source, value in [('absent', 'unrecorded', 0), ('zero', 'local', 0), ('imported', 'xmp', 3)]:
        response = regular_client.get('/api/photo/provenance', params={'path': PATHS[name]})
        assert response.status_code == 200, response.text
        record = next(row for row in response.json()['review'] if row['field'] == 'star_rating')
        assert record['value'] == value and record['source'] == source
        assert response.json()['review_scope'] == 'personal'
    assert snapshot() == before


def test_unknown_catalog_stars_are_not_reported_as_recorded_zero(regular_client, ratings, monkeypatch):
    from api import db_helpers
    monkeypatch.setattr(db_helpers, 'is_multi_user_enabled', lambda: False)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET star_rating=NULL WHERE path=?', (PATHS['absent'],))
    before = snapshot()
    result = regular_client.get('/api/photo/provenance', params={'path': PATHS['absent']})
    assert result.status_code == 200, result.text
    stars = next(row for row in result.json()['review'] if row['field'] == 'star_rating')
    assert result.json()['review_scope'] == 'catalog'
    assert stars['value'] is None
    listed = regular_client.get('/api/photos/paths', params={'path_prefix': VISIBLE, 'max_star_rating': '0',
                                                          'hide_blinks': '0', 'hide_bursts': '0', 'hide_duplicates': '0', 'type': ''})
    assert listed.status_code == 200, listed.text
    assert set(listed.json()['paths']) == {PATHS['personal']}
    assert snapshot() == before


def test_saved_zero_star_membership_uses_owner_scope_for_owner_and_recipient(edition_client, ratings):
    from fastapi.testclient import TestClient
    from api import create_app
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) '
                     'SELECT ?,photo_path,star_rating FROM user_preferences WHERE user_id=? AND photo_path LIKE ?',
                     ('test', 'u1', PREFIX + '%'))
    created = edition_client.post('/api/albums', json={'name': 'zero-star scope fixture', 'is_smart': True,
        'smart_filter_json': json.dumps({'path_prefix': VISIBLE, 'min_star_rating': '0', 'max_star_rating': '0'})})
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        opened = edition_client.get(f'/api/albums/{album}/photos')
        assert opened.status_code == 200, opened.text
        expected = {PATHS['absent'], PATHS['zero']}
        assert {photo['path'] for photo in opened.json()['photos']} == expected
        shared = edition_client.post(f'/api/albums/{album}/share')
        assert shared.status_code == 200, shared.text
        viewed = TestClient(create_app()).get(f'/api/shared/album/{album}', params={'token': shared.json()['share_token']})
        assert viewed.status_code == 200, viewed.text
        assert set(shared_photo_paths(viewed.json()['photos'])) == expected
        assert 'smart_filter_json' not in viewed.json()['album']
    finally:
        deleted = edition_client.delete(f'/api/albums/{album}')
        assert deleted.status_code == 200, deleted.text
