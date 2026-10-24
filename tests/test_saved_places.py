"""Saved coordinates use real schema and shared photo fixtures."""
import sqlite3
from unittest.mock import patch

import pytest

from api.auth import CurrentUser, require_edition
from api.database import get_db
from db.schema import init_database


@pytest.fixture(autouse=True)
def clear_places():
    with get_db() as conn, conn:
        conn.execute('DELETE FROM saved_places')
        conn.execute('DELETE FROM recent_places')
    yield
    with get_db() as conn, conn:
        conn.execute('DELETE FROM saved_places')
        conn.execute('DELETE FROM recent_places')


def test_places_crud_and_assignment(edition_client, seed_photos_prefix):
    path = '/savedplaces/photo.jpg'
    seed_photos_prefix('/savedplaces/', [{'path': path, 'filename': 'photo.jpg'}])
    response = edition_client.post('/api/places', json={'name': '  Straße  ', 'latitude': 0, 'longitude': 0})
    assert response.status_code == 201
    place = response.json()
    assert place['name'] == 'Straße'
    assert edition_client.post('/api/places', json={'name': 'STRASSE', 'latitude': 2, 'longitude': 2}).status_code == 409
    assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': 0, 'gps_longitude': 0, 'saved_place_id': place['id']}).status_code == 200
    listing = edition_client.get('/api/places').json()
    assert next(p for p in listing['places'] if p['id'] == place['id'])['use_count'] == 1
    assert listing['recent'][0]['latitude'] == 0
    assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': 1, 'gps_longitude': 0, 'saved_place_id': place['id']}).status_code == 409
    assert edition_client.get('/api/places').json() == listing
    assert edition_client.delete(f"/api/places/{place['id']}").status_code == 200


@pytest.mark.parametrize('lat,lon', [(91, 0), (0, -181), (None, 0)])
def test_invalid_gps(edition_client, lat, lon):
    assert edition_client.put('/api/photo/gps', json={'path': '/missing', 'gps_latitude': lat, 'gps_longitude': lon}).status_code == 422


def test_rescan_keeps_manual_coordinates(tmp_path):
    from processing.scorer import _photos_upsert
    db = tmp_path / 'photos.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photos(path, filename, gps_latitude, gps_longitude, gps_manually_set) VALUES ('p', 'p', 4, 5, 1)")
        sql = _photos_upsert('INSERT OR REPLACE INTO photos(path, filename, gps_latitude, gps_longitude) VALUES (?, ?, ?, ?)')
        conn.execute(sql, ('p', 'p', 1, 2))
        assert conn.execute('SELECT gps_latitude,gps_longitude FROM photos').fetchone() == (4, 5)
        conn.execute('UPDATE photos SET gps_latitude=NULL,gps_longitude=NULL')
        conn.execute(sql, ('p', 'p', 1, 2))
        assert conn.execute('SELECT gps_latitude,gps_longitude FROM photos').fetchone() == (None, None)


@pytest.mark.parametrize('name', ['', '   ', 'x' * 121])
def test_name_validation(edition_client, name):
    assert edition_client.post('/api/places', json={'name': name, 'latitude': 0, 'longitude': 0}).status_code == 422


@pytest.mark.parametrize('lat,lon', [('NaN', 0), ('Infinity', 0), (0, '-Infinity'), (-90.01, 0), (0, 180.01)])
def test_finite_coordinates(edition_client, lat, lon):
    assert edition_client.post('/api/places', json={'name': 'invalid', 'latitude': lat, 'longitude': lon}).status_code == 422
    assert edition_client.put('/api/photo/gps', json={'path': '/missing', 'gps_latitude': lat, 'gps_longitude': lon}).status_code == 422


def test_owner_isolation_and_missing_id(edition_client):
    with patch('api.routers.places.is_multi_user_enabled', return_value=True):
        created = edition_client.post('/api/places', json={'name': 'Home', 'latitude': 1, 'longitude': 2}).json()
        app = edition_client.app
        app.dependency_overrides[require_edition] = lambda: CurrentUser(user_id='other', edition_authenticated=True)
        assert edition_client.get('/api/places').json() == {'places': [], 'recent': []}
        for place_id in (created['id'], created['id'] + 999):
            assert edition_client.delete(f'/api/places/{place_id}').status_code == 404
            assert edition_client.put(f'/api/places/{place_id}', json={'name': 'Other', 'latitude': 0, 'longitude': 0}).status_code == 404
        app.dependency_overrides[require_edition] = lambda: CurrentUser(edition_authenticated=True)
        assert edition_client.get('/api/places').status_code == 401


def test_single_user_owner_stable_between_auth_identities(edition_client):
    with patch('api.routers.places.is_multi_user_enabled', return_value=False):
        created = edition_client.post('/api/places', json={'name': 'Home', 'latitude': -90, 'longitude': 180}).json()
        for identity in ('_legacy', 'admin', None):
            edition_client.app.dependency_overrides[require_edition] = lambda uid=identity: CurrentUser(user_id=uid, edition_authenticated=True)
            assert edition_client.get('/api/places').json()['places'][0]['id'] == created['id']


def test_place_cap_and_rename_at_cap(edition_client):
    for i in range(100):
        response = edition_client.post('/api/places', json={'name': f'Place {i}', 'latitude': 0, 'longitude': 0})
        assert response.status_code == 201
    assert edition_client.post('/api/places', json={'name': 'over', 'latitude': 0, 'longitude': 0}).status_code == 409
    assert edition_client.put(f"/api/places/{response.json()['id']}", json={'name': 'Renamed', 'latitude': 1, 'longitude': 1}).status_code == 200


def test_recent_unique_bounded_clear_and_failure(edition_client, seed_photos_prefix):
    path = '/placesrecent/a.jpg'
    seed_photos_prefix('/placesrecent/', [{'path': path, 'filename': 'a.jpg'}])
    for i in range(22):
        assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': i, 'gps_longitude': 0}).status_code == 200
    listing = edition_client.get('/api/places').json()
    assert len(listing['recent']) == 20
    assert {r['latitude'] for r in listing['recent']} == set(range(2, 22))
    assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': 21, 'gps_longitude': 0}).status_code == 200
    assert len(edition_client.get('/api/places').json()['recent']) == 20
    before_clear = edition_client.get('/api/places').json()
    assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': None, 'gps_longitude': None}).json() == {'gps_latitude': None, 'gps_longitude': None}
    assert edition_client.get('/api/places').json() == before_clear
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (path,)).fetchone()) == (None, None, 1)
    assert edition_client.put('/api/photo/gps', json={'path': '/missing', 'gps_latitude': 1, 'gps_longitude': 2}).status_code == 404
    assert edition_client.get('/api/places').json() == before_clear


def test_invisible_photo_and_unowned_bookmark_are_atomic(edition_client, seed_photos_prefix):
    path = '/placeshidden/a.jpg'
    seed_photos_prefix('/placeshidden/', [{'path': path, 'filename': 'a.jpg', 'gps_latitude': 8, 'gps_longitude': 9}])
    place = edition_client.post('/api/places', json={'name': 'Office', 'latitude': 1, 'longitude': 2}).json()
    before = edition_client.get('/api/places').json()
    payload = {'path': path, 'gps_latitude': 1, 'gps_longitude': 2, 'saved_place_id': place['id']}
    with patch('api.routers.map.get_visibility_clause', return_value=('0=1', [])):
        assert edition_client.put('/api/photo/gps', json=payload).status_code == 404
    assert edition_client.get('/api/places').json() == before
    with patch('api.routers.places.is_multi_user_enabled', return_value=True):
        assert edition_client.put('/api/photo/gps', json=payload).status_code == 404
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (path,)).fetchone()) == (8, 9, 0)
    assert edition_client.get('/api/places').json() == before


def test_database_failure_rolls_back_photo_usage_history(edition_client, seed_photos_prefix):
    path = '/placesrollback/a.jpg'
    seed_photos_prefix('/placesrollback/', [{'path': path, 'filename': 'a.jpg'}])
    place = edition_client.post('/api/places', json={'name': 'Work', 'latitude': 1, 'longitude': 2}).json()
    from db.places import record_assignment
    def fail_after_usage(*args):
        record_assignment(*args)
        raise sqlite3.OperationalError('injected failure')
    before = edition_client.get('/api/places').json()
    with patch('api.routers.map.places.record_assignment', side_effect=fail_after_usage):
        assert edition_client.put('/api/photo/gps', json={'path': path, 'gps_latitude': 1, 'gps_longitude': 2, 'saved_place_id': place['id']}).status_code == 500
    assert edition_client.get('/api/places').json() == before
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (path,)).fetchone()) == (None, None, 0)


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity'])
def test_nonfinite_json_numbers_rejected(edition_client, token):
    response = edition_client.put('/api/photo/gps', content='{"path":"/missing","gps_latitude":' + token + ',"gps_longitude":0}', headers={'Content-Type': 'application/json'})
    assert response.status_code == 422


def test_schema_upgrade_keeps_photos_and_adds_places(tmp_path):
    db = tmp_path / 'upgrade.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photos(path,filename,gps_latitude,gps_longitude) VALUES ('p','p',1,2)")
        conn.execute('ALTER TABLE photos DROP COLUMN gps_manually_set')
        conn.execute('DROP TABLE saved_places')
        conn.execute('DROP TABLE recent_places')
    init_database(str(db))
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos').fetchone() == (1, 2, 0)
        assert conn.execute('SELECT COUNT(*) FROM saved_places').fetchone() == (0,)
        assert conn.execute('SELECT COUNT(*) FROM recent_places').fetchone() == (0,)


def test_bookmark_edits_do_not_move_assigned_photo(edition_client, seed_photos_prefix):
    path = '/placesedit/a.jpg'
    seed_photos_prefix('/placesedit/', [{'path': path, 'filename': 'a.jpg'}])
    place = edition_client.post('/api/places', json={'name': 'A' * 120, 'latitude': 1, 'longitude': 2}).json()
    assert set(place) == {'id', 'name', 'latitude', 'longitude', 'last_used_at', 'use_count'}
    assert place['last_used_at'] is None and place['use_count'] == 0
    payload = {'path': path, 'gps_latitude': 1, 'gps_longitude': 2, 'saved_place_id': place['id']}
    assert edition_client.put('/api/photo/gps', json=payload).json() == {'gps_latitude': 1, 'gps_longitude': 2}
    updated = edition_client.put(f"/api/places/{place['id']}", json={'name': 'Moved', 'latitude': 3, 'longitude': 4}).json()
    assert updated['use_count'] == 1 and isinstance(updated['last_used_at'], str)
    assert edition_client.put('/api/photo/gps', json=payload).status_code == 409
    assert edition_client.delete(f"/api/places/{place['id']}").json() == {'success': True}
    assert edition_client.put('/api/photo/gps', json=payload).status_code == 404
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (path,)).fetchone()) == (1, 2, 1)
    assert len(edition_client.get('/api/places').json()['recent']) == 1


def test_places_openapi_contract(edition_client):
    schema = edition_client.app.openapi()
    models = schema['components']['schemas']
    assert set(models['SavedPlace']['properties']) == {'id', 'name', 'latitude', 'longitude', 'last_used_at', 'use_count'}
    assert set(models['RecentPlace']['properties']) == {'latitude', 'longitude', 'last_used_at'}
    assert set(models['PlacesResponse']['required']) == {'places', 'recent'}
    assert models['GpsUpdateRequest']['properties']['saved_place_id']['anyOf'] == [{'type': 'integer'}, {'type': 'null'}]
    assert schema['paths']['/api/places']['post']['responses']['201']['content']['application/json']['schema'] == {'$ref': '#/components/schemas/SavedPlace'}
    assert schema['paths']['/api/photo/gps']['put']['responses']['200']['content']['application/json']['schema'] == {'$ref': '#/components/schemas/GpsUpdateResponse'}


def test_batch_gps_preview_apply_and_only_missing(edition_client, seed_photos_prefix):
    prefix = '/batchgps/'
    seed_photos_prefix(prefix, [
        {'path': prefix + 'missing.jpg', 'filename': 'missing.jpg'},
        {'path': prefix + 'partial.jpg', 'filename': 'partial.jpg', 'gps_latitude': 9},
        {'path': prefix + 'existing.jpg', 'filename': 'existing.jpg', 'gps_latitude': 8, 'gps_longitude': 9},
        {'path': prefix + 'excluded.jpg', 'filename': 'excluded.jpg'},
    ])
    body = {'filters': {'folder': prefix}, 'exclude': [prefix + 'excluded.jpg'],
            'gps_latitude': 1, 'gps_longitude': 2, 'only_missing': True, 'preview': True}
    preview = edition_client.post('/api/photos/batch_gps', json=body)
    assert preview.status_code == 200
    assert (preview.json()['changed'], preview.json()['skipped']) == (2, 1)
    body['preview_token'] = preview.json()['preview_token']
    with get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE path LIKE ? AND gps_manually_set=1', (prefix + '%',)).fetchone()[0] == 0
    body['preview'] = False
    assert edition_client.post('/api/photos/batch_gps', json=body).json()['changed'] == 2
    assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 409
    body['preview'] = True
    again = edition_client.post('/api/photos/batch_gps', json=body).json()
    assert (again['changed'], again['skipped']) == (0, 3)
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (prefix + 'partial.jpg',)).fetchone()) == (1, 2, 1)
        assert conn.execute('SELECT gps_latitude FROM photos WHERE path=?', (prefix + 'excluded.jpg',)).fetchone()[0] is None


def test_batch_gps_explicit_visibility_exclusion_duplicates_and_place_recheck(edition_client, seed_photos_prefix):
    paths = ['/batchgpspaths/a.jpg', '/batchgpspaths/b.jpg']
    seed_photos_prefix('/batchgpspaths/', [{'path': p, 'filename': p} for p in paths])
    place = edition_client.post('/api/places', json={'name': 'Batch', 'latitude': 1, 'longitude': 2}).json()
    body = {'photo_paths': paths + paths + ['/absent'], 'exclude': [paths[1]],
            'gps_latitude': 1, 'gps_longitude': 2, 'saved_place_id': place['id'], 'preview': True}
    preview = edition_client.post('/api/photos/batch_gps', json=body).json()
    assert (preview['changed'], preview['skipped']) == (1, 0)
    body['preview_token'] = preview['preview_token']
    assert edition_client.get('/api/places').json()['places'][0]['use_count'] == 0
    with patch('api.routers.map.get_visibility_clause', return_value=('0=1', [])):
        body['preview'] = False
        assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 409
    edition_client.put(f"/api/places/{place['id']}", json={'name': 'Moved', 'latitude': 3, 'longitude': 4})
    assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 409
    edition_client.delete(f"/api/places/{place['id']}")
    assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 404
    with get_db() as conn:
        assert conn.execute('SELECT gps_latitude FROM photos WHERE path=?', (paths[0],)).fetchone()[0] is None


@pytest.mark.parametrize('extra', [
    {'gps_latitude': None}, {'gps_latitude': 'NaN'}, {'gps_longitude': 181},
    {'photo_paths': ['x'] * 1001}, {'filters': {}},
])
def test_batch_gps_validation(edition_client, extra):
    body = {'photo_paths': ['x'], 'gps_latitude': 1, 'gps_longitude': 2}
    body.update(extra)
    assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 422


def test_batch_gps_rejects_same_count_substitution_and_coordinate_changes(edition_client, seed_photos_prefix):
    prefix = '/batchgpsstale/'
    paths = [prefix + 'a.jpg', prefix + 'b.jpg']
    seed_photos_prefix(prefix, [{'path': p, 'filename': p, 'camera_model': 'Before'} for p in paths])
    body = {'filters': {'camera': 'Before'}, 'gps_latitude': 1, 'gps_longitude': 2, 'preview': True}
    preview = edition_client.post('/api/photos/batch_gps', json=body).json()
    body.update(preview=False, preview_token=preview['preview_token'])
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET gps_latitude=8 WHERE path=?', (paths[0],))
    assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 409
    body['preview'] = True
    body['preview_token'] = edition_client.post('/api/photos/batch_gps', json=body).json()['preview_token']
    body['preview'] = False
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET camera_model=? WHERE path=?', ('After', paths[0]))
        conn.execute('INSERT INTO photos(path,filename,camera_model) VALUES (?,?,?)', (prefix + 'c.jpg', 'c.jpg', 'Before'))
    assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 409
    with get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE path LIKE ? AND gps_manually_set=1', (prefix + '%',)).fetchone()[0] == 0


def test_batch_gps_bounded_scope_and_chunked_apply(edition_client, seed_photos_prefix):
    prefix = '/batchgpscap/'
    paths = [prefix + str(i) + '.jpg' for i in range(1001)]
    seed_photos_prefix(prefix, [{'path': p, 'filename': p} for p in paths])
    body = {'filters': {'folder': prefix}, 'gps_latitude': 1, 'gps_longitude': 2, 'preview': True}
    assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 412
    body['exclude'] = [paths[-1]]
    preview = edition_client.post('/api/photos/batch_gps', json=body).json()
    assert preview['changed'] == 1000
    body.update(preview=False, preview_token=preview['preview_token'])
    assert edition_client.post('/api/photos/batch_gps', json=body).json()['changed'] == 1000
    with get_db() as conn:
        assert conn.execute('SELECT gps_latitude FROM photos WHERE path=?', (paths[-1],)).fetchone()[0] is None


def test_batch_gps_failure_rolls_back_and_unchanged_coordinates_are_skipped(edition_client, seed_photos_prefix):
    path = '/batchgpsrollback/a.jpg'
    seed_photos_prefix('/batchgpsrollback/', [{'path': path, 'filename': path, 'gps_latitude': 1, 'gps_longitude': 2}])
    body = {'photo_paths': [path], 'gps_latitude': 1, 'gps_longitude': 2, 'preview': True, 'only_missing': False}
    assert edition_client.post('/api/photos/batch_gps', json=body).json()['skipped'] == 1
    body['gps_latitude'] = 3
    preview = edition_client.post('/api/photos/batch_gps', json=body).json()
    body.update(preview=False, preview_token=preview['preview_token'])
    with patch('api.routers.map.places.record_assignment', side_effect=sqlite3.OperationalError('injected')):
        assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 500
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (path,)).fetchone()) == (1, 2, 0)


def test_batch_gps_revalidates_place_owner_and_records_one_assignment(edition_client, seed_photos_prefix):
    prefix = '/batchgpsowner/'
    paths = [prefix + 'a.jpg', prefix + 'b.jpg']
    seed_photos_prefix(prefix, [{'path': p, 'filename': p} for p in paths])
    place = edition_client.post('/api/places', json={'name': 'Batch work', 'latitude': 1, 'longitude': 2}).json()
    body = {'photo_paths': paths, 'gps_latitude': 1, 'gps_longitude': 2, 'saved_place_id': place['id'], 'preview': True}
    preview = edition_client.post('/api/photos/batch_gps', json=body).json()
    body.update(preview=False, preview_token=preview['preview_token'])
    with patch('api.routers.places.is_multi_user_enabled', return_value=True):
        assert edition_client.post('/api/photos/batch_gps', json=body).status_code == 404
    assert edition_client.post('/api/photos/batch_gps', json=body).json()['changed'] == 2
    listing = edition_client.get('/api/places').json()
    assert listing['places'][0]['use_count'] == 1
    assert len(listing['recent']) == 1


@pytest.mark.parametrize('preview', [True, False], ids=['preview-read-lock', 'apply-write-lock'])
def test_batch_gps_preview_does_not_reserve_writer_lock(edition_client, seed_photos_prefix, preview):
    path = '/batchgpslocking/a.jpg'
    seed_photos_prefix('/batchgpslocking/', [{'path': path, 'filename': path}])
    body = {'photo_paths': [path], 'gps_latitude': 1, 'gps_longitude': 2, 'preview': True}
    snapshot = edition_client.post('/api/photos/batch_gps', json=body).json()
    body.update(preview=preview, preview_token=snapshot['preview_token'])
    from api.routers.map import _gps_batch_scopes

    def check_scanner_lock(conn, *args):
        # A separate scanner connection can reserve the writer slot during a
        # read preview, while an apply must already own that slot.
        db_path = conn.execute('PRAGMA database_list').fetchone()[2]
        with sqlite3.connect(db_path, timeout=0) as scanner:
            if preview:
                scanner.execute('BEGIN IMMEDIATE')
                scanner.rollback()
            else:
                with pytest.raises(sqlite3.OperationalError, match='locked'):
                    scanner.execute('BEGIN IMMEDIATE')
        yield from _gps_batch_scopes(conn, *args)

    with patch('api.routers.map._gps_batch_scopes', side_effect=check_scanner_lock):
        response = edition_client.post('/api/photos/batch_gps', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['changed'] == 1
    with get_db() as conn:
        assert conn.execute('SELECT gps_manually_set FROM photos WHERE path=?', (path,)).fetchone()[0] == (0 if preview else 1)


def test_batch_gps_api_protects_existing_locations_by_default(edition_client, seed_photos_prefix):
    prefix = '/batchgpsdefault/'
    missing, existing = prefix + 'missing.jpg', prefix + 'existing.jpg'
    seed_photos_prefix(prefix, [
        {'path': missing, 'filename': missing},
        {'path': existing, 'filename': existing, 'gps_latitude': 8, 'gps_longitude': 9},
    ])
    body = {'photo_paths': [missing, existing], 'gps_latitude': 1, 'gps_longitude': 2, 'preview': True}
    preview = edition_client.post('/api/photos/batch_gps', json=body).json()
    assert (preview['changed'], preview['skipped']) == (1, 1)
    body.update(preview=False, preview_token=preview['preview_token'])
    assert edition_client.post('/api/photos/batch_gps', json=body).json()['changed'] == 1
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (existing,)).fetchone()) == (8, 9, 0)
    body.update(preview=True, only_missing=False)
    preview = edition_client.post('/api/photos/batch_gps', json=body).json()
    assert (preview['changed'], preview['skipped']) == (1, 1)
    body.update(preview=False, preview_token=preview['preview_token'])
    assert edition_client.post('/api/photos/batch_gps', json=body).json()['changed'] == 1
    with get_db() as conn:
        assert tuple(conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (existing,)).fetchone()) == (1, 2, 1)
