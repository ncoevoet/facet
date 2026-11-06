"""Junk Sweep kind counts follow visibility and effective rejection state."""

import sqlite3

import pytest

from api.auth import CurrentUser, get_optional_user
from api.routers import filter_options
from db import DEFAULT_DB_PATH


PREFIX = '/junk-count-scope/'


@pytest.fixture
def candidates(seed_photos_prefix, monkeypatch):
    from api import config
    import api.db_helpers as helpers
    from api.routers import gallery

    seed_photos_prefix(PREFIX, [
        {'path': PREFIX + 'a.jpg', 'filename': 'a.jpg', 'junk_kind': 'meme', 'is_rejected': 0},
        {'path': PREFIX + 'b.jpg', 'filename': 'b.jpg', 'junk_kind': 'meme', 'is_rejected': 1},
        {'path': PREFIX + 'c.jpg', 'filename': 'c.jpg', 'junk_kind': 'screenshot', 'is_rejected': 0},
        {'path': PREFIX + 'clean.jpg', 'filename': 'clean.jpg', 'junk_kind': 'not_junk'},
        {'path': PREFIX + 'unknown.jpg', 'filename': 'unknown.jpg', 'junk_kind': None},
    ])
    monkeypatch.setattr(helpers, 'is_multi_user_enabled', lambda: False)
    monkeypatch.setattr(config, 'is_multi_user_enabled', lambda: False)
    def visibility(user_id):
        return 'photos.path LIKE ?', [PREFIX + '%']
    monkeypatch.setattr(helpers, 'get_visibility_clause', visibility)
    monkeypatch.setattr(gallery, 'get_visibility_clause', visibility)
    monkeypatch.setattr(filter_options, 'get_visibility_clause', visibility)
    yield
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM user_preferences WHERE photo_path LIKE ?', [PREFIX + '%'])
        conn.execute('DELETE FROM logical_assets WHERE id IN (SELECT asset_id FROM logical_asset_members WHERE photo_path LIKE ?)',
                     [PREFIX + '%'])


def counts(client):
    response = client.get('/api/filter_options/junk_kinds')
    assert response.status_code == 200, response.text
    assert response.json()['cached'] is False
    return dict(response.json()['junk_kinds'])


@pytest.fixture
def logical_pair(candidates):
    from db import logical_assets, logical_review

    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('INSERT INTO photos(path, filename, junk_kind, is_rejected) VALUES (?, ?, ?, 0)',
                     [PREFIX + 'a.CR2', 'a.CR2', 'receipt'])
        key = logical_assets.create(conn, [PREFIX + 'a.jpg', PREFIX + 'a.CR2'], PREFIX + 'a.CR2',
                                    visibility_sql='1=1')
        logical_review.seed(conn, key, PREFIX + 'a.jpg', 1, visibility_sql='1=1')
    yield key
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM logical_review_fields WHERE asset_id=?', [key])
        for table in ('logical_review_seeds', 'logical_review_versions', 'logical_review_field_versions'):
            conn.execute(f'DELETE FROM {table} WHERE asset_id=?', [key])
        conn.execute('DELETE FROM logical_assets WHERE id=?', [key])


def queue(client):
    response = client.get('/api/photos', params={
        'type': '', 'junk_kind': 'any', 'hide_rejected': '1',
        'hide_blinks': '0', 'hide_bursts': '0', 'hide_duplicates': '0', 'collapse_stacks': '0',
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_remaining_counts_exclude_rejected_and_clean_rows_without_using_offline_cache(
    edition_client, candidates, monkeypatch,
):
    import db

    stale_cache = []

    def cached(*args, **kwargs):
        stale_cache.append(args)
        return [['meme', 99]], True

    monkeypatch.setattr(db, 'get_cached_stat', cached)
    assert counts(edition_client) == {'meme': 1, 'screenshot': 1}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET is_rejected=1 WHERE path=?', [PREFIX + 'a.jpg'])
    assert counts(edition_client) == {'screenshot': 1}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET is_rejected=0 WHERE path=?', [PREFIX + 'a.jpg'])
    assert counts(edition_client) == {'meme': 1, 'screenshot': 1}
    assert stale_cache == []


def test_counts_use_each_readers_preferences_and_reauthorize_their_visibility(
    edition_client, candidates, monkeypatch,
):
    import api.db_helpers as helpers
    from api import config
    from api.routers import gallery

    monkeypatch.setattr(helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(config, 'is_multi_user_enabled', lambda: True)
    owner = [CurrentUser(user_id='junk-reader-a', role='user')]
    edition_client.app.dependency_overrides[get_optional_user] = lambda: owner[0]
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('INSERT INTO user_preferences (user_id, photo_path, is_rejected) VALUES (?, ?, 1)',
                     ['junk-reader-a', PREFIX + 'a.jpg'])
    # A's own rejection hides a.jpg; the global rejection of b.jpg does not.
    assert counts(edition_client) == {'meme': 1, 'screenshot': 1}
    owner[0] = CurrentUser(user_id='junk-reader-b', role='user')
    assert counts(edition_client) == {'meme': 2, 'screenshot': 1}
    monkeypatch.setattr(gallery, 'get_visibility_clause',
                        lambda user_id: ('photos.path = ?', [PREFIX + 'c.jpg']))
    assert counts(edition_client) == {'screenshot': 1}
    owner[0] = CurrentUser(user_id='junk-reader-a', role='user')
    monkeypatch.setattr(gallery, 'get_visibility_clause', lambda user_id: ('photos.path LIKE ?', [PREFIX + '%']))
    assert counts(edition_client) == {'meme': 1, 'screenshot': 1}


def test_counts_do_not_reveal_candidates_when_visibility_denies_anonymous_reader(
    anonymous_client, candidates, monkeypatch,
):
    seen = []

    def deny(user_id):
        seen.append(user_id)
        return '0=1', []

    from api.routers import gallery
    monkeypatch.setattr(gallery, 'get_visibility_clause', deny)
    assert counts(anonymous_client) == {}
    # The scope is built once per candidate kind, always for the anonymous reader.
    assert seen and set(seen) == {None}


def test_logical_pair_counts_only_primary_kind_and_honors_logical_rejection(edition_client, logical_pair):
    assert counts(edition_client) == {'receipt': 1, 'screenshot': 1}
    listing = queue(edition_client)
    assert listing['total'] == 2
    assert {photo['path'] for photo in listing['photos']} == {PREFIX + 'a.CR2', PREFIX + 'c.jpg'}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('INSERT INTO logical_review_fields VALUES (?, ?, ?, ?, ?)',
                     [logical_pair, '', 'decision', 2, 'user'])
    assert counts(edition_client) == {'screenshot': 1}
    assert queue(edition_client)['total'] == 1
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT is_rejected FROM photos WHERE path IN (?, ?) ORDER BY path',
                            [PREFIX + 'a.jpg', PREFIX + 'a.CR2']).fetchall() == [(0,), (0,)]


def test_partial_visibility_keeps_authorized_file_without_hidden_primary_or_review_inheritance(
    edition_client, logical_pair, monkeypatch,
):
    import api.db_helpers as helpers
    from api.routers import gallery

    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('INSERT INTO logical_review_fields VALUES (?, ?, ?, ?, ?)',
                     [logical_pair, '', 'decision', 2, 'user'])

    def visible_file(user_id):
        return 'photos.path = ?', [PREFIX + 'a.jpg']

    monkeypatch.setattr(helpers, 'get_visibility_clause', visible_file)
    monkeypatch.setattr(gallery, 'get_visibility_clause', visible_file)
    assert counts(edition_client) == {'meme': 1}
    listing = queue(edition_client)
    assert listing['total'] == 1
    assert [photo['path'] for photo in listing['photos']] == [PREFIX + 'a.jpg']


def test_logical_counts_respect_each_account_decision(edition_client, logical_pair, monkeypatch):
    from api import config
    import api.db_helpers as helpers

    monkeypatch.setattr(helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(config, 'is_multi_user_enabled', lambda: True)
    owner = [CurrentUser(user_id='junk-reader-a', role='user')]
    edition_client.app.dependency_overrides[get_optional_user] = lambda: owner[0]
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('INSERT INTO logical_review_fields VALUES (?, ?, ?, ?, ?)',
                     [logical_pair, 'junk-reader-a', 'decision', 2, 'user'])
    assert counts(edition_client) == {'meme': 1, 'screenshot': 1}
    assert queue(edition_client)['total'] == 2
    owner[0] = CurrentUser(user_id='junk-reader-b', role='user')
    assert counts(edition_client) == {'receipt': 1, 'meme': 1, 'screenshot': 1}
    assert queue(edition_client)['total'] == 3
    owner[0] = CurrentUser(user_id='junk-reader-a', role='user')
    assert counts(edition_client) == {'meme': 1, 'screenshot': 1}


def test_junk_queue_ignores_configured_gallery_type(edition_client, candidates, monkeypatch):
    from api.routers import gallery

    monkeypatch.setitem(gallery.VIEWER_CONFIG['defaults'], 'type', 'portrait')
    assert counts(edition_client) == {'meme': 1, 'screenshot': 1}
    assert queue(edition_client)['total'] == 2
