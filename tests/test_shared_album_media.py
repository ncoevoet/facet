"""Real temporary files prove token-scoped media bytes and live membership refusal."""

import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from tests.conftest import _TEST_DB_FILE


@pytest.fixture
def shared_media(tmp_path, seed_photos_prefix, album_factory, monkeypatch):
    from api.config import VIEWER_CONFIG

    monkeypatch.setitem(VIEWER_CONFIG, 'password', 'fixture-protected-install')
    prefix = str(tmp_path) + '/'
    path = prefix + 'chosen.jpg'
    other = prefix + 'other.jpg'
    for target in (path, other):
        Image.new('RGB', (24, 16), (32, 64, 96)).save(target)
    data = Path(path).read_bytes()
    seed_photos_prefix(prefix, [
        {'path': path, 'filename': 'chosen.jpg', 'thumbnail': data},
        {'path': other, 'filename': 'other.jpg', 'thumbnail': data},
    ])
    album = album_factory(prefix, 'fixture-album-media', 'Chosen')(
        member_names=('chosen.jpg',))
    return album, path, other, data


def _asset(album, path, token='fixture-album-media'):
    from api.shared_assets import shared_asset_reference

    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        row_id = conn.execute('SELECT rowid FROM photos WHERE path=?', (path,)).fetchone()[0]
    return shared_asset_reference(album, token, row_id, path)


@pytest.mark.parametrize('kind', ['thumbnail', 'image', 'download'])
def test_protected_anonymous_member_bytes_only(kind, shared_media, anonymous_client):
    album, path, other, data = shared_media
    base = f'/api/shared/album/{album}/media/{kind}'
    response = anonymous_client.get(base, params={'asset_id': _asset(album, path), 'token': 'fixture-album-media'})
    assert response.status_code == 200, response.text
    assert response.content == data
    assert response.headers['cache-control'] == 'private, no-store'
    for target, token in [(other, 'fixture-album-media'), (path, 'invalid'), (path, '')]:
        refused = anonymous_client.get(base, params={'asset_id': _asset(album, target), 'token': token})
        assert refused.status_code == 404
    # Public album tokens must not authenticate the ordinary library endpoints.
    ordinary = anonymous_client.get('/api/' + kind,
                                    params={'path': path, 'token': 'fixture-album-media'})
    assert ordinary.status_code == 404


def test_member_removal_and_revocation_refuse_even_previously_cached_bytes(shared_media,
                                                                         anonymous_client):
    album, path, _, _ = shared_media
    url = f'/api/shared/album/{album}/media/thumbnail'
    params = {'asset_id': _asset(album, path), 'token': 'fixture-album-media'}
    first = anonymous_client.get(url, params=params)
    assert first.status_code == 200
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('DELETE FROM album_photos WHERE album_id = ?', (album,))
    assert anonymous_client.get(url, params=params).status_code == 404
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('INSERT INTO album_photos(album_id, photo_path, position) VALUES (?, ?, 0)',
                     (album, path))
        conn.execute('UPDATE albums SET share_token = NULL WHERE id = ?', (album,))
    assert anonymous_client.get(url, params=params).status_code == 404


def test_shared_download_refuses_ungranted_raw_companion(shared_media, anonymous_client):
    album, path, _, _ = shared_media
    response = anonymous_client.get(f'/api/shared/album/{album}/media/download',
                                    params={'asset_id': _asset(album, path), 'token': 'fixture-album-media',
                                            'type': 'raw'})
    assert response.status_code == 422
    assert response.headers['cache-control'] == 'private, no-store'


def test_offline_original_download_error_is_not_cacheable(shared_media, anonymous_client):
    album, path, _, _ = shared_media
    Path(path).unlink()
    response = anonymous_client.get(f'/api/shared/album/{album}/media/download',
                                    params={'asset_id': _asset(album, path), 'token': 'fixture-album-media'})
    assert response.status_code == 404
    assert response.headers['cache-control'] == 'private, no-store'


def test_smart_membership_is_rechecked_after_saved_criteria_change(shared_media,
                                                                 album_factory,
                                                                 anonymous_client):
    album, path, _, data = shared_media
    smart = album_factory(str(Path(path).parent) + '/', 'smart-media', 'Smart')(
        smart_filter={'path_prefix': str(Path(path).parent) + '/', 'no_capture_date': '1'})
    url = f'/api/shared/album/{smart}/media/thumbnail'
    params = {'asset_id': _asset(smart, path, 'smart-media'), 'token': 'smart-media'}
    assert anonymous_client.get(url, params=params).content == data
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET date_taken = ? WHERE path = ?',
                     ('2026:11:01 10:00:00', path))
    assert anonymous_client.get(url, params=params).status_code == 404


def test_owner_visibility_is_rechecked_and_public_metadata_hides_manual_tags(
        shared_media, anonymous_client, monkeypatch):
    from api.config import _FULL_CONFIG
    from db.manual_tags import insert_manual_tag

    album, path, _, _ = shared_media
    owner = {'directories': [str(Path(path).parent)]}
    monkeypatch.setitem(_FULL_CONFIG, 'users', {'test': owner})
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        insert_manual_tag(conn, path, 'private-owner-note')
    try:
        params = {'asset_id': _asset(album, path), 'token': 'fixture-album-media'}
        url = f'/api/shared/album/{album}/photo'
        response = anonymous_client.get(url, params=params)
        assert response.status_code == 200, response.text
        assert response.json()['asset_id'] == params['asset_id']
        assert path not in response.text
        assert 'private-owner-note' not in response.text
        assert response.headers['cache-control'] == 'private, no-store'
        owner['directories'] = []
        assert anonymous_client.get(url, params=params).status_code == 404
        assert anonymous_client.get(f'/api/shared/album/{album}/media/thumbnail',
                                     params=params).status_code == 404
    finally:
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute('DELETE FROM photo_manual_tags WHERE photo_path = ?', (path,))


def test_public_asset_projection_contains_no_native_path_and_media_uses_only_asset_id(shared_media, anonymous_client):
    album, path, _, data = shared_media
    scope = {'token': 'fixture-album-media'}
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE albums SET cover_photo_path=? WHERE id=?', (path, album))
    response = anonymous_client.get(f'/api/shared/album/{album}', params=scope)
    assert response.status_code == 200, response.text
    assert path not in response.text and str(Path(path).parent) not in response.text
    assert 'cover_photo_path' not in response.json()['album']
    photo = response.json()['photos'][0]
    assert 'path' not in photo and photo['filename'] == 'chosen.jpg'
    asset_id = photo['asset_id']
    assert response.json()['album']['cover_asset_id'] == asset_id
    for kind in ('thumbnail', 'image', 'download'):
        actual = anonymous_client.get(f'/api/shared/album/{album}/media/{kind}', params={**scope, 'asset_id': asset_id})
        assert actual.status_code == 200, actual.text
        assert actual.content == data
        old = anonymous_client.get(f'/api/shared/album/{album}/media/{kind}', params={**scope, 'path': path})
        assert old.status_code == 422
    detail = anonymous_client.get(f'/api/shared/album/{album}/photo', params={**scope, 'asset_id': asset_id})
    assert detail.status_code == 200 and detail.json()['asset_id'] == asset_id
    assert path not in detail.text
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE albums SET share_token=NULL WHERE id=?', (album,))
    revoked = anonymous_client.get(f'/api/shared/album/{album}/media/image', params={**scope, 'asset_id': asset_id})
    assert revoked.status_code == 404


def test_signed_asset_refuses_tampering_cross_album_and_changed_row_path(shared_media, anonymous_client):
    from api.shared_assets import shared_asset_reference

    album, path, other, _ = shared_media
    asset = _asset(album, path)
    url = f'/api/shared/album/{album}/media/thumbnail'
    scope = {'token': 'fixture-album-media'}
    tampered = asset[:-1] + ('a' if asset[-1] != 'a' else 'b')
    row_id = int(asset.split('.')[0])
    cross_album = shared_asset_reference(album + 1, scope['token'], row_id, path)
    for reference in (tampered, cross_album, '/private/native.jpg'):
        response = anonymous_client.get(url, params={**scope, 'asset_id': reference})
        assert response.status_code == 404
        assert path not in response.text
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET path=? WHERE rowid=?', (other + '.replacement', row_id))
    assert anonymous_client.get(url, params={**scope, 'asset_id': asset}).status_code == 404
