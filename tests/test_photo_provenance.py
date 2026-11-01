"""Current authority must be read-only, account-scoped and path/actor redacted."""

import sqlite3

import pytest

from db import DEFAULT_DB_PATH

PATH = '/provenance-tests/photo.jpg'


@pytest.fixture
def photo(seed_photos_prefix):
    seed_photos_prefix('/provenance-tests/', [{
        'path': PATH, 'filename': 'photo.jpg', 'star_rating': 2,
        'date_manually_set': 1, 'gps_manually_set': 0,
    }])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM photo_manual_tags WHERE photo_path=?', (PATH,))
        conn.execute('UPDATE photos SET star_rating=4 WHERE path=?', (PATH,))
        conn.execute("INSERT INTO photo_manual_tags(photo_path,tag,source,created_by) VALUES (?,?,?,?)",
                     (PATH, 'imported', 'xmp', 'private-other-user'))
        conn.execute("INSERT INTO photo_manual_tags(photo_path,tag,source,created_by) VALUES (?,?,?,?)",
                     (PATH, 'typed', 'user', 'private-other-user'))
        conn.execute("UPDATE photo_metadata_edits SET source='xmp',source_path=?,source_at=? "
                     "WHERE photo_path=? AND user_id='' AND field='star_rating'",
                     ('/private/other-library/secret.xmp', '2026-01-01T00:00:00Z', PATH))
    yield PATH
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM photo_manual_tags WHERE photo_path=?', (PATH,))


def snapshot():
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        return {table: conn.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall()
                for table in ('photos', 'photo_metadata_edits', 'photo_manual_tags', 'user_preferences')}


def test_read_only_catalog_sources_redact_paths_and_actors(regular_client, photo):
    before = snapshot()
    result = regular_client.get('/api/photo/provenance', params={'path': photo})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['review_scope'] == 'catalog'
    stars = next(row for row in body['review'] if row['field'] == 'star_rating')
    assert stars['source'] == 'xmp' and stars['value'] == 4
    assert stars['source_at'] == '2026-01-01T00:00:00Z'
    favorite = next(row for row in body['review'] if row['field'] == 'is_favorite')
    assert favorite['source'] == 'unrecorded' and favorite['value'] == 0
    assert body['manual_tags'] == [{'tag': 'imported', 'source': 'xmp'}, {'tag': 'typed', 'source': 'user'}]
    assert body['capture_date_override'] is True and body['gps_override'] is False
    assert 'private-other-user' not in result.text and 'secret.xmp' not in result.text
    assert 'source_path' not in result.text and 'created_by' not in result.text
    assert snapshot() == before


def test_personal_sources_never_adopt_catalog_or_other_user_receipts(regular_client, photo, monkeypatch):
    from api import db_helpers
    monkeypatch.setattr(db_helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(db_helpers, 'get_user_directories', lambda user: ['/provenance-tests'])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,?)',
                     ('u1', photo, 3))
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,star_rating) VALUES (?,?,?)',
                     ('other-user', photo, 5))
        conn.execute('UPDATE user_preferences SET star_rating=0 WHERE user_id=? AND photo_path=?', ('u1', photo))
    before = snapshot()
    result = regular_client.get('/api/photo/provenance', params={'path': photo})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['review_scope'] == 'personal'
    stars = next(row for row in body['review'] if row['field'] == 'star_rating')
    assert stars['value'] == 0 and stars['source'] == 'local'
    assert stars['source_at'] is None
    assert 'other-user' not in result.text
    assert snapshot() == before


def test_invisible_missing_and_share_requests_do_not_disclose(regular_client, photo, monkeypatch):
    assert regular_client.get('/api/photo/provenance', params={'path': photo, 'token': 'share'}).status_code == 404
    from api import db_helpers
    monkeypatch.setattr(db_helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(db_helpers, 'get_user_directories', lambda user: ['/another-library'])
    denied = regular_client.get('/api/photo/provenance', params={'path': photo})
    missing = regular_client.get('/api/photo/provenance', params={'path': '/missing.jpg'})
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


def test_protected_anonymous_request_refused(anonymous_client, photo, monkeypatch):
    from api.auth import VIEWER_CONFIG
    monkeypatch.setitem(VIEWER_CONFIG, 'password', 'test-protected-viewer')
    result = anonymous_client.get('/api/photo/provenance', params={'path': photo})
    assert result.status_code == 401


def test_later_local_reset_replaces_import_receipt_and_bounds_legacy_tag_rows(regular_client, photo):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET star_rating=0 WHERE path=?', (photo,))
        conn.executemany('INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES (?,?,?)',
                         [(photo, f'legacy-{i:02}', 'user') for i in range(51)])
    result = regular_client.get('/api/photo/provenance', params={'path': photo})
    assert result.status_code == 200, result.text
    body = result.json()
    stars = next(row for row in body['review'] if row['field'] == 'star_rating')
    assert stars['value'] == 0 and stars['source'] == 'local' and stars['source_at'] is None
    assert len(body['manual_tags']) == 50 and body['manual_tags_truncated'] is True


def test_database_failure_is_not_empty_sources(regular_client, photo, monkeypatch):
    from api.routers import gallery

    def failed_read():
        raise sqlite3.OperationalError('private database path is unavailable')

    monkeypatch.setattr(gallery, 'get_db', failed_read)
    result = regular_client.get('/api/photo/provenance', params={'path': photo})
    assert result.status_code == 503
    assert result.json() == {'detail': 'Metadata sources could not be read'}
