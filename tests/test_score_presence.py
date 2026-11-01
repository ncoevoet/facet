"""Explicit NULL measurement policies keep range and action scopes identical."""

import json
import sqlite3

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from api import create_app
from api.agent.tools_read import SearchFilters
from api.agent.ui_tools import UiFilterPatch
from api.models.gallery import GalleryParams
from api.routers.gallery import _build_gallery_where
from db import DEFAULT_DB_PATH
from tests.test_gallery_match_logic import _photo, library as library
from tests.test_person_match_groups import PREFIX, OWNER, group as group, owner_client as owner_client


def _matches(conn, **filters):
    clauses, args = _build_gallery_where(filters, conn)
    return {row[0] for row in conn.execute('SELECT path FROM photos WHERE ' + ' AND '.join(clauses or ['1=1']), args)}


def test_missing_and_zero_and_bounds_are_distinct_per_metric(library):
    for name, value in [('missing', None), ('zero', 0), ('low', 1), ('match', 3), ('high', 9)]:
        _photo(library, '/' + name, tech_sharpness=value, face_quality=0 if value == 3 else None, camera_model='A')
    bounds = {'min_sharpness': '2', 'max_sharpness': '4'}
    assert _matches(library, **bounds) == {'/match'}
    assert _matches(library, **bounds, score_presence='{"min_sharpness":"include_missing"}') == {'/match', '/missing'}
    assert _matches(library, **bounds, score_presence='{"min_sharpness":"missing_only"}') == {'/missing'}
    assert _matches(library, score_presence='{"min_sharpness":"measured_only"}') == {'/zero', '/low', '/match', '/high'}
    assert _matches(library, **bounds, score_presence='{"min_sharpness":"include_missing","min_face_quality":"measured_only"}') == {'/match'}
    assert _matches(library, **bounds, camera='B', score_presence='{"min_sharpness":"include_missing"}') == set()


@pytest.mark.parametrize('raw', ['null', '[]', '{"min_star_rating":"missing_only"}', '{"min_iso":"missing_only"}',
                                '{"min_sharpness":true}', '{"min_sharpness":"anything"}',
                                '{"min_sharpness":"missing_only","min_sharpness":"include_missing"}', 'x' * 5001])
def test_bad_policy_refuses_models_and_raw_saved_rules_fail_closed(library, raw):
    _photo(library, '/present', tech_sharpness=3)
    for model in [GalleryParams, SearchFilters, UiFilterPatch]:
        with pytest.raises(ValidationError):
            model(score_presence=raw)
    assert _matches(library, score_presence=raw) == set()


def test_read_saved_and_excluded_write_share_authorized_missing_policy(owner_client, group):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        for name, value in [('alice/one.jpg', None), ('alice/two.jpg', 0), ('alice/both.jpg', 3), ('alice/none.jpg', 9), ('bob/foreign.jpg', None)]:
            conn.execute('UPDATE photos SET tech_sharpness=? WHERE path=?', (value, PREFIX + name))
    filters = {'score_presence': '{"min_sharpness":"include_missing"}', 'min_sharpness': '2', 'max_sharpness': '4', 'path_prefix': PREFIX, 'type': '', 'hide_bursts': '0'}
    expected = {PREFIX + 'alice/one.jpg', PREFIX + 'alice/both.jpg'}
    listing = owner_client.get('/api/photos', params=filters)
    assert listing.status_code == 200, listing.text
    assert {r['path'] for r in listing.json()['photos']} == expected
    assert owner_client.get('/api/photos/count', params=filters).json()['total'] == 2
    assert set(owner_client.get('/api/photos/paths', params=filters).json()['paths']) == expected
    rows = owner_client.post('/api/photos/by_paths', json={'paths': [r['path'] for r in group], 'filters': filters})
    assert rows.status_code == 200, rows.text
    assert {r['path'] for r in rows.json()['photos']} == expected
    created = owner_client.post('/api/albums', json={'name': 'missing scores', 'is_smart': True, 'smart_filter_json': json.dumps(filters)})
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        opened = owner_client.get(f'/api/albums/{album}/photos')
        assert opened.status_code == 200, opened.text
        assert {r['path'] for r in opened.json()['photos']} == expected
    finally:
        owner_client.delete(f'/api/albums/{album}')
    applied = owner_client.post('/api/photos/batch_rating', json={'filters': filters, 'exclude': [PREFIX + 'alice/one.jpg'], 'rating': 4})
    assert applied.status_code == 200, applied.text
    assert applied.json()['count'] == 1
    refused = owner_client.post('/api/photos/batch_rating', json={'filters': {**filters, 'score_presence': '{"min_sharpness":false}'}, 'rating': 5})
    assert refused.status_code == 422, refused.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert dict(conn.execute('SELECT photo_path,star_rating FROM user_preferences WHERE user_id=? AND photo_path LIKE ?', (OWNER, PREFIX + '%'))) == {PREFIX + 'alice/both.jpg': 4}


@pytest.mark.parametrize(('column', 'minimum', 'maximum'), [
    ('topiq_score', 'min_topiq', 'max_topiq'),
    ('narrative_moment_confidence', 'min_moment_confidence', 'max_moment_confidence'),
    ('channel_clip_shadow_pct', 'min_channel_clip_shadow', 'max_channel_clip_shadow'),
])
def test_manual_shared_album_preserves_every_registry_bound_with_missing_policy(owner_client, group, column, minimum, maximum):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        for name, value in [('one.jpg', None), ('two.jpg', 0), ('both.jpg', .3), ('none.jpg', .9)]:
            conn.execute(f'UPDATE photos SET {column}=? WHERE path=?', (value, PREFIX + 'alice/' + name))
    created = owner_client.post('/api/albums', json={'name': 'shared measurement bounds', 'is_smart': False})
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        added = owner_client.post(f'/api/albums/{album}/photos', json={'photo_paths': [row['path'] for row in group if '/alice/' in row['path']]})
        assert added.status_code == 200, added.text
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('INSERT INTO album_photos(album_id,photo_path) VALUES (?,?)', (album, PREFIX + 'bob/foreign.jpg'))
        shared = owner_client.post(f'/api/albums/{album}/share')
        assert shared.status_code == 200, shared.text
        viewed = TestClient(create_app()).get(f'/api/shared/album/{album}', params={
            'token': shared.json()['share_token'], minimum: '.2', maximum: '.4',
            'score_presence': json.dumps({minimum: 'include_missing'}),
        })
        assert viewed.status_code == 200, viewed.text
        assert {row['path'] for row in viewed.json()['photos']} == {PREFIX + 'alice/one.jpg', PREFIX + 'alice/both.jpg'}
    finally:
        owner_client.delete(f'/api/albums/{album}')
