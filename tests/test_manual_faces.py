"""Manual face marks use canonical pixels, real schema, and transactional writes."""
import base64
import json
from io import BytesIO
import sqlite3
from uuid import uuid4

import pytest
import numpy as np
from PIL import Image

from api.database import get_db


@pytest.fixture
def manual_photo(tmp_path, seed_photos_prefix, monkeypatch):
    from api import config
    # Test originals belong to this temporary library, independent of any
    # operator scan roots/path mapping in the running checkout's local config.
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {})
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    path = str(tmp_path / 'manual.jpg')
    image = Image.new('RGB', (100, 80), 'red')
    image.paste('blue', (50, 0, 100, 80))
    image.save(path)
    seed_photos_prefix(str(tmp_path), [{'path': path, 'filename': 'manual.jpg', 'image_width': 100, 'image_height': 80}])
    return path


def frame(client, path):
    response = client.get('/api/photo/manual-face-frame', params={'path': path})
    assert response.status_code == 200, response.text
    return response.json()


def payload(client, path, **overrides):
    return {'path': path, 'frame_token': frame(client, path)['frame_token'],
            'bbox': [0.55, 0.1, 0.95, 0.9], 'new_person_name': 'Manual Alice',
            'client_id': str(uuid4()), **overrides}


def test_zero_detection_create_crop_retry_edit_delete(edition_client, manual_photo):
    data = payload(edition_client, manual_photo)
    preview = frame(edition_client, manual_photo)
    assert (preview['width'], preview['height']) == (100, 80)
    assert Image.open(BytesIO(base64.b64decode(preview['image_base64']))).size == (100, 80)
    response = edition_client.post('/api/photo/manual-faces', json=data)
    assert response.status_code == 201, response.text
    region = response.json()
    assert region['person_name'] == 'Manual Alice'
    assert region['bbox'] == data['bbox'] and region['source_changed'] is False
    assert edition_client.post('/api/photo/manual-faces', json=data).json() == region
    with get_db() as conn:
        row = conn.execute('SELECT * FROM faces WHERE id=?', (region['id'],)).fetchone()
        assert row['is_manual'] == 1 and row['face_index'] < 0 and row['embedding'] == b''
        assert row['confidence'] is None and row['landmark_2d_106'] is None
        crop = Image.open(BytesIO(row['face_thumbnail']))
        red, _, blue = crop.getpixel((crop.width // 2, crop.height // 2))
        assert blue > red + 100
        assert conn.execute('SELECT COUNT(*) FROM persons WHERE id=?', (region['person_id'],)).fetchone()[0] == 1
    assert edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).json() == {'regions': [region]}
    update = {k: v for k, v in data.items() if k != 'client_id'}
    update.update(bbox=[0.05, 0.1, 0.4, 0.9], new_person_name='Manual Bob')
    changed = edition_client.put(f"/api/photo/manual-faces/{region['id']}", json=update)
    assert changed.status_code == 200, changed.text
    assert changed.json()['person_name'] == 'Manual Bob'
    repeated = edition_client.put(f"/api/photo/manual-faces/{region['id']}", json=update)
    assert repeated.status_code == 200
    assert repeated.json()['person_id'] == changed.json()['person_id']
    with get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM persons WHERE name=?', ('Manual Bob',)).fetchone()[0] == 1
    assert edition_client.delete(f"/api/photo/manual-faces/{region['id']}", params={'path': manual_photo}).json() == {'success': True}
    assert edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).json() == {'regions': []}


@pytest.mark.parametrize('bbox', [[0, 0, 0, 1], [0.5, 0, 0.1, 1], [-0.1, 0, 0.2, 1], [0, 0, 1.1, 1], [0, 0, 0.01, 0.01], ['NaN', 0, 1, 1]])
def test_invalid_box_changes_nothing(edition_client, manual_photo, bbox):
    response = edition_client.post('/api/photo/manual-faces', json=payload(edition_client, manual_photo, bbox=bbox))
    assert response.status_code == 422, response.text
    with get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM faces WHERE photo_path=?', (manual_photo,)).fetchone()[0] == 0


def test_stale_source_keeps_saved_mark_reviewable(edition_client, manual_photo):
    data = payload(edition_client, manual_photo)
    created = edition_client.post('/api/photo/manual-faces', json=data)
    assert created.status_code == 201
    Image.new('RGB', (120, 90), 'green').save(manual_photo)
    assert edition_client.post('/api/photo/manual-faces', json={**data, 'client_id': str(uuid4())}).status_code == 409
    listed = edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).json()['regions']
    assert listed[0]['source_changed'] is True
    assert listed[0]['bbox'] == data['bbox']


def test_person_identity_keys_new_people_independent(edition_client, manual_photo):
    with get_db() as conn, conn:
        first = conn.execute("INSERT INTO persons(name) VALUES ('First')").lastrowid
        second = conn.execute("INSERT INTO persons(name) VALUES ('Second')").lastrowid
        keys = [r[0] for r in conn.execute('SELECT person_key FROM persons WHERE id IN (?,?)', (first, second))]
    assert len(set(keys)) == 2 and all(keys)


def test_frame_never_reads_an_unregistered_local_file(edition_client, tmp_path, monkeypatch):
    from utils import manual_face_frame as module
    file = tmp_path / 'private.jpg'
    Image.new('RGB', (20, 20)).save(file)
    def forbidden_decode(*args):
        pytest.fail('Unregistered path reached decoder')
    monkeypatch.setattr(module, 'load_image_for_face_crop', forbidden_decode)
    assert edition_client.get('/api/photo/manual-face-frame', params={'path': str(file)}).status_code == 404


def test_frame_rechecks_access_after_slow_decode(edition_client, manual_photo, monkeypatch):
    from api.routers import manual_faces as module
    from utils import manual_face_frame as frames
    original = frames.load_image_for_face_crop
    revoked = False
    def visibility(*args):
        if revoked:
            raise LookupError('Photo not found')
    def decode(path):
        nonlocal revoked
        pixels = original(path)
        revoked = True
        return pixels
    monkeypatch.setattr(module, 'assert_photo_visible', visibility)
    monkeypatch.setattr(frames, 'load_image_for_face_crop', decode)
    assert edition_client.get('/api/photo/manual-face-frame', params={'path': manual_photo}).status_code == 404


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity'])
def test_raw_json_nonfinite_is_422(edition_client, manual_photo, token):
    data = payload(edition_client, manual_photo)
    body = json.dumps(data).replace('[0.55,', '[' + token + ',')
    assert edition_client.post('/api/photo/manual-faces', content=body, headers={'Content-Type': 'application/json'}).status_code == 422


def test_create_rollback_has_no_orphan_person(edition_client, manual_photo, monkeypatch):
    from api.routers import manual_faces as module
    data = payload(edition_client, manual_photo, new_person_name='Unique Rollback Person')
    def fail(*args):
        raise sqlite3.OperationalError('injected after face and person insert')
    monkeypatch.setattr(module, 'refresh_person_counts', fail)
    assert edition_client.post('/api/photo/manual-faces', json=data).status_code == 500
    with get_db() as conn:
        assert conn.execute('SELECT 1 FROM persons WHERE name=?', (data['new_person_name'],)).fetchone() is None
        assert conn.execute('SELECT 1 FROM faces WHERE photo_path=?', (manual_photo,)).fetchone() is None


def test_frame_token_is_not_a_login_token(edition_client, manual_photo):
    import asyncio
    from fastapi.security import HTTPAuthorizationCredentials
    from starlette.requests import Request
    from api.auth import get_optional_user
    token = frame(edition_client, manual_photo)['frame_token']
    request = Request({'type': 'http', 'method': 'GET', 'headers': []})
    assert asyncio.run(get_optional_user(request, HTTPAuthorizationCredentials(scheme='Bearer', credentials=token))) is None


def test_region_limits_existing_target_and_access(edition_client, manual_photo, monkeypatch, seed_photos_prefix):
    from api import config
    with get_db() as conn, conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Existing Visible')").lastrowid
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id,bbox_x1,bbox_y1,bbox_x2,bbox_y2) "
                     "VALUES (?,0,?,?,1,1,5,5)", (manual_photo, np.ones(512, dtype=np.float32).tobytes(), pid))
    data = payload(edition_client, manual_photo, person_id=pid, new_person_name=None)
    created = edition_client.post('/api/photo/manual-faces', json=data)
    assert created.status_code == 201, created.text
    assert created.json()['person_id'] == pid
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': []}}})
    assert edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).status_code == 404
    assert edition_client.delete(f"/api/photo/manual-faces/{created.json()['id']}", params={'path': manual_photo}).status_code == 404
    assert edition_client.post('/api/photo/manual-faces', json={**data, 'client_id': str(uuid4())}).status_code == 404


def test_hidden_target_person_is_rejected_atomically(edition_client, manual_photo, monkeypatch, seed_photos_prefix):
    from api import config
    from pathlib import Path
    hidden = '/manualhidden/secret.jpg'
    seed_photos_prefix('/manualhidden/', [{'path': hidden, 'filename': 'secret.jpg'}])
    with get_db() as conn, conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Private Person')").lastrowid
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,0,X'01',?)", (hidden, pid))
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': [str(Path(manual_photo).parent)]}}})
    data = payload(edition_client, manual_photo, person_id=pid, new_person_name=None)
    assert edition_client.post('/api/photo/manual-faces', json=data).status_code == 404
    with get_db() as conn:
        assert conn.execute('SELECT 1 FROM faces WHERE photo_path=?', (manual_photo,)).fetchone() is None


def test_cap_applies_only_to_new_marks_and_retry_stays_idempotent(edition_client, manual_photo):
    data = payload(edition_client, manual_photo)
    region = edition_client.post('/api/photo/manual-faces', json=data).json()
    with get_db() as conn, conn:
        conn.executemany("INSERT INTO faces(photo_path,face_index,embedding,is_manual,manual_key) VALUES (?,?,X'',1,?)",
                         [(manual_photo, -i - 2, str(uuid4())) for i in range(99)])
    assert edition_client.post('/api/photo/manual-faces', json={**data, 'client_id': str(uuid4())}).status_code == 409
    assert edition_client.post('/api/photo/manual-faces', json=data).json()['id'] == region['id']
    assert edition_client.put(f"/api/photo/manual-faces/{region['id']}", json={k: v for k, v in data.items() if k != 'client_id'}).status_code == 200


def test_non_edition_cannot_read_frame_or_regions(regular_client, manual_photo):
    for route in ('manual-faces', 'manual-face-frame'):
        assert regular_client.get('/api/photo/' + route, params={'path': manual_photo}).status_code == 403


def test_expired_wrong_photo_and_wrong_user_tokens(edition_client, manual_photo):
    from datetime import timedelta
    from api.auth import CurrentUser, create_access_token, decode_access_token, require_edition
    data = payload(edition_client, manual_photo)
    claims = decode_access_token(data['frame_token'])
    expired = create_access_token(claims, expires_delta=timedelta(seconds=-1))
    assert edition_client.post('/api/photo/manual-faces', json={**data, 'frame_token': expired}).status_code == 409
    foreign = create_access_token({**claims, 'path': '/other'})
    assert edition_client.post('/api/photo/manual-faces', json={**data, 'frame_token': foreign}).status_code == 409
    edition_client.app.dependency_overrides[require_edition] = lambda: CurrentUser(user_id='different', edition_authenticated=True)
    assert edition_client.post('/api/photo/manual-faces', json=data).status_code == 409


def test_manual_api_cannot_edit_or_remove_automatic_detection(edition_client, manual_photo):
    with get_db() as conn, conn:
        fid = conn.execute("INSERT INTO faces(photo_path,face_index,embedding) VALUES (?,0,X'01')", (manual_photo,)).lastrowid
    data = payload(edition_client, manual_photo)
    assert edition_client.put(f'/api/photo/manual-faces/{fid}', json=data).status_code == 404
    assert edition_client.delete(f'/api/photo/manual-faces/{fid}', params={'path': manual_photo}).status_code == 404


def test_creation_rejects_existing_detected_overlap(edition_client, manual_photo):
    with get_db() as conn, conn:
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,bbox_x1,bbox_y1,bbox_x2,bbox_y2) "
                     "VALUES (?,0,X'01',55,8,95,72)", (manual_photo,))
    response = edition_client.post('/api/photo/manual-faces', json=payload(edition_client, manual_photo))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'detected_face_overlap'


def test_metadata_export_uses_manual_frame_and_omits_stale_mark(edition_client, manual_photo):
    from api.routers.export import _fetch_regions_map
    from processing.xmp_export import _cli_face_regions
    data = payload(edition_client, manual_photo)
    before = open(manual_photo, 'rb').read()
    assert edition_client.post('/api/photo/manual-faces', json=data).status_code == 201
    assert open(manual_photo, 'rb').read() == before
    with get_db() as conn, conn:
        # Backfilled/stale photo dimensions must not redefine the manual frame.
        conn.execute('UPDATE photos SET image_width=10,image_height=8 WHERE path=?', (manual_photo,))
        regions = _fetch_regions_map(conn, [manual_photo])[manual_photo]
        assert regions[0].x == pytest.approx(0.75)
        assert regions[0].w == pytest.approx(0.4)
        assert _cli_face_regions(conn, manual_photo, 10, 8)[0].w == pytest.approx(0.4)
    Image.new('RGB', (100, 80), 'green').save(manual_photo)
    with get_db() as conn:
        assert not _fetch_regions_map(conn, [manual_photo]).get(manual_photo)
        assert _cli_face_regions(conn, manual_photo, 100, 80) == []


@pytest.mark.parametrize('orientation', range(1, 9))
def test_editor_uses_upright_canonical_pixels(edition_client, manual_photo, orientation):
    from PIL import ImageOps
    image = Image.new('RGB', (100, 80), 'red')
    image.paste('blue', (50, 0, 100, 80))
    exif = Image.Exif()
    exif[274] = orientation
    image.save(manual_photo, exif=exif)
    with Image.open(manual_photo) as original:
        expected = ImageOps.exif_transpose(original).copy()
    result = frame(edition_client, manual_photo)
    actual = Image.open(BytesIO(base64.b64decode(result['image_base64'])))
    assert actual.size == expected.size == (result['width'], result['height'])
    for x, y in ((10, 10), (actual.width - 10, actual.height - 10)):
        assert max(abs(a - b) for a, b in zip(actual.getpixel((x, y)), expected.getpixel((x, y)))) < 10


def test_manual_assignment_tracks_person_rename_merge_and_delete(edition_client, manual_photo):
    alice = edition_client.post('/api/photo/manual-faces', json=payload(edition_client, manual_photo)).json()
    bob = edition_client.post('/api/photo/manual-faces', json=payload(
        edition_client, manual_photo, bbox=[0.1, 0.1, 0.4, 0.9], new_person_name='Merge Bob')).json()
    assert edition_client.post(f"/api/persons/{alice['person_id']}/rename", json={'name': 'Renamed Alice'}).status_code == 200
    listed = edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).json()['regions']
    assert next(r for r in listed if r['id'] == alice['id'])['person_name'] == 'Renamed Alice'
    assert edition_client.post('/api/persons/merge', json={'source_id': alice['person_id'], 'target_id': bob['person_id']}).status_code == 200
    listed = edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).json()['regions']
    assert {r['person_id'] for r in listed} == {bob['person_id']}
    assert edition_client.post(f"/api/persons/{bob['person_id']}/delete").status_code == 200
    listed = edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).json()['regions']
    assert len(listed) == 2 and all(r['person_id'] is None and r['person_name'] is None for r in listed)


def test_manual_edit_preserves_viewer_cached_recognition_centroid(edition_client, manual_photo):
    cached = np.ones(512, dtype=np.float32).tobytes()
    with get_db() as conn, conn:
        pid = conn.execute("INSERT INTO persons(name,centroid,centroid_model) VALUES ('Cached Person',?,'arcface_buffalo_l')", (cached,)).lastrowid
        # Viewer export deliberately strips recognition embeddings.
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,0,X'',?)", (manual_photo, pid))
    data = payload(edition_client, manual_photo, person_id=pid, new_person_name=None)
    created = edition_client.post('/api/photo/manual-faces', json=data)
    assert created.status_code == 201
    with get_db() as conn:
        assert conn.execute('SELECT centroid FROM persons WHERE id=?', (pid,)).fetchone()[0] == cached
    assert edition_client.delete(f"/api/photo/manual-faces/{created.json()['id']}", params={'path': manual_photo}).status_code == 200
    with get_db() as conn:
        assert conn.execute('SELECT centroid FROM persons WHERE id=?', (pid,)).fetchone()[0] == cached


def test_updating_manual_crop_refreshes_stored_representative_avatar(edition_client, manual_photo):
    data = payload(edition_client, manual_photo, bbox=[0.05, 0.1, 0.4, 0.9])
    created = edition_client.post('/api/photo/manual-faces', json=data).json()
    changed = {k: v for k, v in data.items() if k != 'client_id'}
    changed.update(bbox=[0.55, 0.1, 0.95, 0.9], person_id=created['person_id'], new_person_name=None)
    assert edition_client.put(f"/api/photo/manual-faces/{created['id']}", json=changed).status_code == 200
    with get_db() as conn:
        row = conn.execute('SELECT p.face_thumbnail AS avatar,f.face_thumbnail AS crop FROM persons p JOIN faces f '
                           'ON p.representative_face_id=f.id WHERE f.id=?', (created['id'],)).fetchone()
        assert row['avatar'] == row['crop']


def test_deleted_manual_uuid_cannot_be_reused(edition_client, manual_photo):
    data = payload(edition_client, manual_photo)
    region = edition_client.post('/api/photo/manual-faces', json=data).json()
    assert edition_client.delete(f"/api/photo/manual-faces/{region['id']}", params={'path': manual_photo}).status_code == 200
    assert edition_client.post('/api/photo/manual-faces', json=data).status_code == 409


def test_delete_failure_rolls_back_face_and_deletion_record(edition_client, manual_photo, monkeypatch):
    from api.routers import manual_faces as router
    data = payload(edition_client, manual_photo)
    region = edition_client.post('/api/photo/manual-faces', json=data).json()
    def fail(*args):
        raise sqlite3.OperationalError('injected delete failure')
    monkeypatch.setattr(router, 'refresh_person_counts', fail)
    assert edition_client.delete(f"/api/photo/manual-faces/{region['id']}", params={'path': manual_photo}).status_code == 500
    with get_db() as conn:
        assert conn.execute('SELECT 1 FROM faces WHERE id=?', (region['id'],)).fetchone() is not None
        assert conn.execute('SELECT 1 FROM manual_face_deletions WHERE manual_key=?', (region['manual_key'],)).fetchone() is None


def test_person_gallery_membership_and_warm_counts_follow_manual_changes(edition_client, manual_photo, monkeypatch):
    from api import db_helpers
    from pathlib import Path
    monkeypatch.setattr(db_helpers, 'COUNT_CACHE_TTL', 300)
    with get_db() as conn, conn:
        ada = conn.execute("INSERT INTO persons(name) VALUES ('Gallery Ada')").lastrowid
        bo = conn.execute("INSERT INTO persons(name) VALUES ('Gallery Bo')").lastrowid

    def assert_gallery(person_id, expected):
        params = {'person_id': str(person_id), 'path_prefix': str(Path(manual_photo).parent) + '/',
                  'type': '', 'quality': '', 'hide_blinks': 'false', 'hide_bursts': 'false',
                  'hide_duplicates': 'false', 'hide_brackets': 'false', 'hide_panoramas': 'false'}
        # Repeated real requests warm the shared count cache before each write.
        for _ in range(2):
            listing = edition_client.get('/api/photos', params=params)
            assert listing.status_code == 200, listing.text
            assert {p['path'] for p in listing.json()['photos']} == expected
            assert listing.json()['total'] == len(expected)
            count = edition_client.get('/api/photos/count', params=params)
            assert count.status_code == 200, count.text
            assert count.json()['total'] == len(expected)
        with db_helpers._count_cache_lock:
            assert db_helpers._count_cache  # This regression must exercise warmed counts.

    assert_gallery(ada, set())
    assert_gallery(bo, set())
    data = payload(edition_client, manual_photo, person_id=ada, new_person_name=None)
    created = edition_client.post('/api/photo/manual-faces', json=data)
    assert created.status_code == 201, created.text
    region = created.json()
    assert_gallery(ada, {manual_photo})
    assert_gallery(bo, set())

    update = {key: value for key, value in data.items() if key != 'client_id'}
    update['person_id'] = bo
    assert edition_client.put(f"/api/photo/manual-faces/{region['id']}", json=update).status_code == 200
    assert_gallery(ada, set())
    assert_gallery(bo, {manual_photo})

    assert edition_client.delete(f"/api/photo/manual-faces/{region['id']}", params={'path': manual_photo}).status_code == 200
    assert_gallery(ada, set())
    assert_gallery(bo, set())


def test_review_queue_cached_until_editor_validation_and_cleared_by_save(edition_client, manual_photo, monkeypatch):
    data = payload(edition_client, manual_photo)
    region = edition_client.post('/api/photo/manual-faces', json=data).json()
    def queued():
        response = edition_client.get('/api/photos', params={'manual_faces_need_review': '1'})
        assert response.status_code == 200, response.text
        return [p['path'] for p in response.json()['photos']]
    assert manual_photo not in queued()
    Image.new('RGB', (120, 90), 'green').save(manual_photo)
    assert manual_photo not in queued()
    assert edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).json()['regions'][0]['source_changed']
    from utils import manual_face_frame as frames
    with monkeypatch.context() as patch:
        patch.setattr(frames, 'is_current', lambda *a, **k: pytest.fail('Gallery accessed original'))
        assert manual_photo in queued()
    update = payload(edition_client, manual_photo)
    update.pop('client_id')
    assert edition_client.put(f"/api/photo/manual-faces/{region['id']}", json=update).status_code == 200
    assert manual_photo not in queued()
    with get_db() as conn, conn:
        conn.execute('UPDATE faces SET manual_review_required=1 WHERE id=?', (region['id'],))
    assert manual_photo in queued()
    assert edition_client.delete(f"/api/photo/manual-faces/{region['id']}", params={'path': manual_photo}).status_code == 200
    assert manual_photo not in queued()


def test_review_validation_does_not_overwrite_newer_identity(edition_client, manual_photo, monkeypatch):
    data = payload(edition_client, manual_photo)
    region = edition_client.post('/api/photo/manual-faces', json=data).json()
    from api.routers import manual_faces as module
    def concurrent_edit(*args):
        with get_db() as conn, conn:
            conn.execute('UPDATE faces SET manual_source=?,manual_review_required=0 WHERE id=?',
                         ('newer-editor-frame', region['id']))
        return False
    monkeypatch.setattr(module, '_current', concurrent_edit)
    assert edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).status_code == 200
    with get_db() as conn:
        assert conn.execute('SELECT manual_review_required FROM faces WHERE id=?', (region['id'],)).fetchone()[0] == 0


def test_review_filter_visibility_membership_and_all_filtered_target(edition_client, manual_photo, seed_photos_prefix, monkeypatch):
    region = edition_client.post('/api/photo/manual-faces', json=payload(edition_client, manual_photo)).json()
    other = '/queue-other/current.jpg'
    seed_photos_prefix('/queue-other/', [{'path': other, 'filename': 'current.jpg'}])
    with get_db() as conn, conn:
        conn.execute('UPDATE faces SET manual_review_required=1 WHERE id=?', (region['id'],))
    filters = {'manual_faces_need_review': True}
    matched = edition_client.post('/api/photos/by_paths', json={'paths': [manual_photo, other], 'filters': filters})
    assert matched.status_code == 200, matched.text
    assert [p['path'] for p in matched.json()['photos']] == [manual_photo]
    result = edition_client.post('/api/photos/batch_rating', json={'filters': {'manual_faces_need_review': '1'}, 'rating': 4})
    assert result.status_code == 200, result.text
    with get_db() as conn:
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (manual_photo,)).fetchone()[0] == 4
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (other,)).fetchone()[0] != 4
    from api.routers import gallery
    monkeypatch.setattr(gallery, 'get_visibility_clause', lambda *a, **k: ('photos.path != ?', [manual_photo]))
    hidden = edition_client.get('/api/photos', params={'manual_faces_need_review': '1'})
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()['photos'] == []
    hidden_paths = edition_client.post('/api/photos/by_paths', json={'paths': [manual_photo], 'filters': filters})
    assert hidden_paths.json()['photos'] == []


def test_unavailable_editor_validation_flags_mark_and_rechecks_visibility(edition_client, manual_photo, monkeypatch):
    from pathlib import Path
    region = edition_client.post('/api/photo/manual-faces', json=payload(edition_client, manual_photo)).json()
    Path(manual_photo).unlink()
    response = edition_client.get('/api/photo/manual-faces', params={'path': manual_photo})
    assert response.json()['regions'][0]['source_changed']
    with get_db() as conn:
        assert conn.execute('SELECT manual_review_required FROM faces WHERE id=?', (region['id'],)).fetchone()[0] == 1
    from api.routers import manual_faces as module
    def revoked(*args):
        def deny(*args):
            raise LookupError('Access revoked')
        monkeypatch.setattr(module, 'assert_photo_visible', deny)
        return False
    monkeypatch.setattr(module, '_current', revoked)
    assert edition_client.get('/api/photo/manual-faces', params={'path': manual_photo}).status_code == 404
