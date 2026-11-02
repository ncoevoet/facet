"""Recipient policy and private rule projection, using temporary test database rows."""

import json
import sqlite3

import pytest

from tests.conftest import _TEST_DB_FILE


@pytest.mark.parametrize('smart', [False, True])
def test_recipient_policy_and_private_saved_rules(smart, seed_photos_prefix, album_factory,
                                                 anonymous_client, monkeypatch):
    from api.routers import albums

    prefix = '/recipient-policy/'
    seed_photos_prefix(prefix, [{'path': prefix + 'photo.jpg', 'filename': 'photo.jpg',
                                'camera_model': 'Test camera', 'gps_latitude': 12.0}])
    make = album_factory(prefix, 'recipient-policy-token', 'Public title')
    rules = {'path_prefix': prefix, 'camera': 'private-nonmatching-camera'}
    album_id = make(smart_filter=rules if smart else None, member_names=('photo.jpg',))
    monkeypatch.setitem(albums.VIEWER_CONFIG['features'], 'show_proofing', True)
    response = anonymous_client.get(f'/api/shared/album/{album_id}',
                                    params={'token': 'recipient-policy-token'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert 'smart_filter_json' not in body['album']
    assert 'private-nonmatching-camera' not in response.text
    assert body['sharing_policy'] == {
        'membership': 'smart' if smart else 'manual',
        'membership_can_change': True,
        'downloads': 'album_member_original',
        'photo_metadata': True,
        'native_paths': False,
        'manual_tags': False,
        'saved_rules': False,
        'password_protected': False,
        'expires_at': None,
        'proofing': not smart,
    }
    assert body['proofing_enabled'] is (not smart)
    if not smart:
        assert 'path' not in body['photos'][0]
        assert prefix not in response.text
        assert body['photos'][0]['asset_id']
        assert body['photos'][0]['gps_latitude'] == 12.0
        assert not body['photos'][0].get('manual_tags')
    # Projection must not alter the owner's durable saved criteria.
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        stored = conn.execute('SELECT smart_filter_json FROM albums WHERE id = ?',
                              (album_id,)).fetchone()[0]
    assert (json.loads(stored) if stored else None) == (rules if smart else None)


def test_private_manual_tag_selects_members_without_disclosing_rule_or_tag(
        seed_photos_prefix, album_factory, anonymous_client):
    from db.manual_tags import insert_manual_tag

    prefix = '/recipient-private-rule/'
    path = prefix + 'photo.jpg'
    seed_photos_prefix(prefix, [{'path': path, 'filename': 'photo.jpg'}])
    secret = 'private-client-project-unique'
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        insert_manual_tag(conn, path, secret)
    try:
        album_id = album_factory(prefix, 'private-rule-token', 'Chosen photos')(
            smart_filter={'path_prefix': prefix, 'tag': secret})
        response = anonymous_client.get(f'/api/shared/album/{album_id}',
                                        params={'token': 'private-rule-token'})
        assert response.status_code == 200, response.text
        assert [photo['filename'] for photo in response.json()['photos']] == ['photo.jpg']
        assert path not in response.text
        assert secret not in response.text
        assert 'smart_filter_json' not in response.json()['album']
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            assert conn.execute('SELECT tag FROM photo_manual_tags WHERE photo_path = ?',
                                (path,)).fetchone()[0] == secret
    finally:
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            conn.execute('DELETE FROM photo_manual_tags WHERE photo_path = ?', (path,))


def test_link_does_not_become_library_authorization_on_protected_install(
        seed_photos_prefix, album_factory, anonymous_client, monkeypatch):
    from api.config import VIEWER_CONFIG

    prefix = '/recipient-download-policy/'
    path = prefix + 'photo.jpg'
    seed_photos_prefix(prefix, [{'path': path, 'filename': 'photo.jpg'}])
    album_id = album_factory(prefix, 'protected-link-token', 'Protected')(
        member_names=('photo.jpg',))
    monkeypatch.setitem(VIEWER_CONFIG, 'password', 'fixture-protected-install')
    response = anonymous_client.get(f'/api/shared/album/{album_id}',
                                    params={'token': 'protected-link-token'})
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 1
    assert response.json()['sharing_policy']['downloads'] == 'album_member_original'
    denied = anonymous_client.get('/api/download',
                                  params={'path': path, 'token': 'protected-link-token'})
    assert denied.status_code == 404
