"""One person group has the same authorized members in reads and writes."""

from tests.shared_asset_helpers import shared_photo_paths
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import config, create_app
from api.auth import CurrentUser, get_optional_user, require_authenticated, require_edition
from db import DEFAULT_DB_PATH

PREFIX = '/person-match-group/'
OWNER = 'person-match-alice'
PEOPLE = (987511, 987512)


@pytest.fixture()
def group(seed_photos_prefix):
    rows = [
        {'path': PREFIX + name, 'filename': name.rsplit('/', 1)[-1],
         'camera_model': 'Person Group Camera', 'aggregate': 6.0,
         'date_taken': '2026:10:31 12:00:00'}
        for name in ['alice/one.jpg', 'alice/two.jpg', 'alice/both.jpg', 'alice/none.jpg', 'bob/foreign.jpg']
    ]
    seed_photos_prefix(PREFIX, rows)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.executemany('INSERT INTO persons(id, name) VALUES (?, ?)', zip(PEOPLE, ['Group One', 'Group Two']))
        for name, people in [('alice/one.jpg', PEOPLE[:1]), ('alice/two.jpg', PEOPLE[1:]),
                             ('alice/both.jpg', PEOPLE), ('bob/foreign.jpg', PEOPLE)]:
            for index, person in enumerate(people):
                conn.execute('INSERT INTO faces(photo_path, face_index, embedding, person_id) VALUES (?, ?, ?, ?)',
                             (PREFIX + name, index, b'\x00' * 4, person))
    try:
        yield rows
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DELETE FROM faces WHERE photo_path LIKE ?', (PREFIX + '%',))
            conn.executemany('DELETE FROM persons WHERE id = ?', [(person,) for person in PEOPLE])


@pytest.fixture()
def owner_client(monkeypatch):
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {OWNER: {'directories': [PREFIX + 'alice']}})
    user = CurrentUser(user_id=OWNER, role='user', edition_authenticated=True)
    app = create_app()
    for dependency in [get_optional_user, require_authenticated, require_edition]:
        app.dependency_overrides[dependency] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _filters(mode):
    return {'person_id': ','.join(map(str, PEOPLE)), 'person_match': mode,
            'camera': 'Person Group Camera', 'path_prefix': PREFIX, 'type': '',
            'hide_blinks': '0', 'hide_bursts': '0', 'hide_duplicates': '0',
            'hide_brackets': '0', 'hide_panoramas': '0', 'hide_rejected': '0'}


@pytest.mark.parametrize(('mode', 'names'), [('all', ['both.jpg']), ('any', ['one.jpg', 'two.jpg', 'both.jpg'])])
def test_list_count_paths_and_explicit_rows_share_one_group(owner_client, group, mode, names):
    filters = _filters(mode)
    expected = {PREFIX + 'alice/' + name for name in names}
    listing = owner_client.get('/api/photos', params=filters)
    assert listing.status_code == 200, listing.text
    assert {p['path'] for p in listing.json()['photos']} == expected
    count = owner_client.get('/api/photos/count', params=filters)
    assert count.status_code == 200, count.text
    assert count.json()['total'] == len(expected)
    paths = owner_client.get('/api/photos/paths', params=filters)
    assert paths.status_code == 200, paths.text
    assert set(paths.json()['paths']) == expected
    by_paths = owner_client.post('/api/photos/by_paths', json={'paths': [r['path'] for r in group], 'filters': filters})
    assert by_paths.status_code == 200, by_paths.text
    assert {p['path'] for p in by_paths.json()['photos']} == expected


def test_any_group_write_preserves_excluded_nonmatching_and_foreign_rows(owner_client, group):
    excluded = PREFIX + 'alice/one.jpg'
    result = owner_client.post('/api/photos/batch_rating', json={'filters': _filters('any'), 'exclude': [excluded], 'rating': 4})
    assert result.status_code == 200, result.text
    assert result.json()['count'] == 2
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        rows = conn.execute('SELECT photo_path, star_rating FROM user_preferences WHERE user_id = ? AND photo_path LIKE ?',
                            (OWNER, PREFIX + '%')).fetchall()
    assert dict(rows) == {PREFIX + 'alice/two.jpg': 4, PREFIX + 'alice/both.jpg': 4}


def test_saved_any_group_and_recipient_view_keep_owner_visibility(owner_client, group):
    rules = {'person_id': ','.join(map(str, PEOPLE)), 'person_match': 'any', 'camera': 'Person Group Camera'}
    created = owner_client.post('/api/albums', json={'name': 'person-any', 'is_smart': True, 'smart_filter_json': json.dumps(rules)})
    assert created.status_code == 200, created.text
    album_id = created.json()['id']
    try:
        expected = {PREFIX + 'alice/' + name for name in ['one.jpg', 'two.jpg', 'both.jpg']}
        opened = owner_client.get(f'/api/albums/{album_id}/photos')
        assert opened.status_code == 200, opened.text
        assert {p['path'] for p in opened.json()['photos']} == expected
        shared = owner_client.post(f'/api/albums/{album_id}/share')
        assert shared.status_code == 200, shared.text
        recipient = TestClient(create_app())
        viewed = recipient.get(f'/api/shared/album/{album_id}', params={'token': shared.json()['share_token']})
        assert viewed.status_code == 200, viewed.text
        assert set(shared_photo_paths(viewed.json()['photos'])) == expected
    finally:
        owner_client.delete(f'/api/albums/{album_id}')


def test_invalid_mode_refuses_before_any_batch_write(owner_client, group):
    result = owner_client.post('/api/photos/batch_rating', json={'filters': _filters('some'), 'rating': 5})
    assert result.status_code == 422, result.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM user_preferences WHERE user_id = ? AND photo_path LIKE ?',
                            (OWNER, PREFIX + '%')).fetchone()[0] == 0


def test_agent_contract_and_saved_rules_preserve_any_and_refuse_invalid_modes():
    from pydantic import ValidationError
    from api.agent.album_filters import to_stored
    from api.agent.tools_read import SearchFilters
    from api.agent.ui_tools import UiFilterPatch
    from api.models.gallery import GalleryParams

    for model in [GalleryParams, SearchFilters, UiFilterPatch]:
        assert model(person_match='any').person_match == 'any'
        with pytest.raises(ValidationError):
            model(person_match='unknown')
    error, saved = to_stored({'person': '1,2', 'person_match': 'any'})
    assert error is None and saved == {'person_id': '1,2', 'person_match': 'any'}
    assert to_stored({'person': '1,2', 'person_match': 'all'})[1] == {'person_id': '1,2'}
    assert to_stored({'person_match': 'any'})[1] == {}
    assert to_stored({'person': '1,2', 'person_match': 'unknown'})[0] is not None


@pytest.mark.parametrize('people', ['1,bad', '0,1', '-1,2', '9223372036854775808', ','.join(map(str, range(1, 202)))])
def test_invalid_person_ids_refuse_before_any_filtered_write(owner_client, group, people):
    filters = {**_filters('any'), 'person_id': people}
    result = owner_client.post('/api/photos/batch_rating', json={'filters': filters, 'rating': 5})
    assert result.status_code == 422, result.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM user_preferences WHERE user_id = ? AND photo_path LIKE ?',
                            (OWNER, PREFIX + '%')).fetchone()[0] == 0
