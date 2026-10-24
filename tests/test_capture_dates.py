"""Capture walltime correction: bounded preview, atomic apply, strict dates."""
from unittest.mock import patch

import pytest

from api.database import get_db


def seed(seed_photos_prefix, dates):
    paths = [f'/capture/{i}.jpg' for i in range(len(dates))]
    seed_photos_prefix('/capture/', [dict(path=p, filename=p.rsplit('/', 1)[1], date_taken=d) for p, d in zip(paths, dates)])
    return paths


def values(paths):
    with get_db() as conn:
        return [tuple(conn.execute('SELECT date_taken, date_manually_set FROM photos WHERE path=?', (p,)).fetchone()) for p in paths]


def test_preview_apply_and_replay(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024:02:28 23:59:59', None, '2024-01-01'])
    body = dict(photo_paths=paths, offset_seconds=1)
    preview = edition_client.post('/api/photos/capture_date/preview', json=body)
    assert preview.status_code == 200
    data = preview.json()
    assert (data['changed'], data['skipped']) == (1, 2)
    assert data['samples'][0] == dict(path=paths[0], old_date='2024:02:28 23:59:59', new_date='2024:02:29 00:00:00')
    assert values(paths)[0] == ('2024:02:28 23:59:59', 0)
    applied = edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': data['preview_token']})
    assert applied.status_code == 200
    assert values(paths)[0] == ('2024:02:29 00:00:00', 1)
    assert edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': data['preview_token']}).status_code == 409


@pytest.mark.parametrize('offset', [0, True, 1.5, '1', 31622401, -31622401])
def test_invalid_offset(edition_client, offset):
    assert edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=[], offset_seconds=offset)).status_code == 422


@pytest.mark.parametrize('date', ['2024-01-01', '2024-01-01T12:00:00Z', '2024-01-01T12:00:00.123', '2024:02:30 12:00:00', '2024:01:01 12:00:00garbage', '9999:12:31 23:59:59'])
def test_unsupported_or_overflow_date_skipped(edition_client, seed_photos_prefix, date):
    paths = seed(seed_photos_prefix, [date])
    response = edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=paths, offset_seconds=1))
    assert response.status_code == 200
    assert response.json()['skipped'] == 1
    assert response.json()['changed'] == 0


def test_stale_preview_is_atomic(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024-01-01T12:00:00', '2024-01-01 12:00:00'])
    body = dict(photo_paths=paths, offset_seconds=-3600)
    data = edition_client.post('/api/photos/capture_date/preview', json=body).json()
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET date_taken=? WHERE path=?', ('2025:01:01 12:00:00', paths[1]))
    response = edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': data['preview_token']})
    assert response.status_code == 409
    assert values(paths)[0] == ('2024-01-01T12:00:00', 0)


def test_edition_required(regular_client):
    for action in ('preview', 'apply'):
        assert regular_client.post(f'/api/photos/capture_date/{action}', json=dict(photo_paths=[], offset_seconds=1, preview_token='x')).status_code in (401, 403)
    assert regular_client.delete('/api/photo/capture_date', params={'path': '/capture/0.jpg'}).status_code in (401, 403)


@pytest.mark.parametrize('partial', [False, True])
def test_rescan_preserves_manual_date_pair(tmp_path, partial):
    import sqlite3
    from db.schema import init_database
    from processing.scorer import _PARTIAL_CORE_COLUMNS, _photos_partial_upsert, _photos_upsert
    db = str(tmp_path / 'dates.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photos(path, date_taken, date_manually_set) VALUES ('p','2024:01:01 01:02:03',1)")
        if partial:
            sql = _photos_partial_upsert(('date_manually_set',))
            params = {key: None for key in _PARTIAL_CORE_COLUMNS}
            params.update(path='p', date_taken='2000:01:01 01:02:03', date_manually_set=0)
        else:
            sql = _photos_upsert('INSERT OR REPLACE INTO photos(path,date_taken,date_manually_set) VALUES (?,?,?)')
            params = ('p', '2000:01:01 01:02:03', 0)
        conn.execute(sql, params)
        assert conn.execute('SELECT date_taken,date_manually_set FROM photos').fetchone() == ('2024:01:01 01:02:03', 1)


def test_manual_date_export_only():
    from processing.xmp_export import XmpRating, build_xmp, _exiftool_tag_args
    manual = XmpRating.from_row(dict(date_taken='2024:01:01 01:02:03', date_manually_set=1))
    assert 'exif:DateTimeOriginal="2024-01-01T01:02:03"' in build_xmp(manual)
    assert '-XMP-exif:DateTimeOriginal=2024-01-01T01:02:03' in _exiftool_tag_args(manual, [], [])
    scanned = XmpRating.from_row(dict(date_taken='2024:01:01 01:02:03'))
    assert 'DateTimeOriginal' not in build_xmp(scanned)
    assert not any('DateTimeOriginal' in arg for arg in _exiftool_tag_args(scanned, [], []))


@pytest.mark.parametrize('raw,expected', [('2020:02:29 12:34:56', '2020:02:29 12:34:56'), (None, None)])
def test_reset_restores_or_clears_file_date(edition_client, seed_photos_prefix, tmp_path, raw, expected):
    paths = seed(seed_photos_prefix, ['2024:01:01 01:02:03'])
    disk = tmp_path / 'a.jpg'
    disk.write_bytes(b'original')
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET date_manually_set=1 WHERE path=?', (paths[0],))
    with patch('api.routers.capture_dates.resolve_photo_disk_path', return_value=str(disk)), patch('api.routers.capture_dates.get_exif_batch', return_value={str(disk): {'date_taken': raw}}):
        result = edition_client.delete('/api/photo/capture_date', params={'path': paths[0]})
    assert result.status_code == 200
    assert values(paths) == [(expected, 0)]
    assert disk.read_bytes() == b'original'


@pytest.mark.parametrize('mutation', ['date', 'file', 'access'])
def test_reset_rechecks_after_file_read(edition_client, seed_photos_prefix, tmp_path, mutation, monkeypatch):
    from api import config
    paths = seed(seed_photos_prefix, ['2024:01:01 01:02:03'])
    disk = tmp_path / 'a.jpg'
    disk.write_bytes(b'original')
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': ['/capture']}}})
    def read(_):
        if mutation == 'date':
            with get_db() as conn, conn:
                conn.execute('UPDATE photos SET date_manually_set=1 WHERE path=?', (paths[0],))
        elif mutation == 'file':
            disk.write_bytes(b'changed')
        else:
            config._FULL_CONFIG['users']['test']['directories'] = []
        return {str(disk): {'date_taken': '2000:01:01 00:00:00'}}
    with patch('api.routers.capture_dates.resolve_photo_disk_path', return_value=str(disk)), patch('api.routers.capture_dates.get_exif_batch', side_effect=read):
        result = edition_client.delete('/api/photo/capture_date', params={'path': paths[0]})
    assert result.status_code == (404 if mutation == 'access' else 409)
    assert values(paths)[0][0] == '2024:01:01 01:02:03'


@pytest.mark.parametrize('filtered', [False, True])
def test_scope_exclusions_and_visibility(edition_client, seed_photos_prefix, monkeypatch, filtered):
    from api import config
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'] * 3)
    monkeypatch.setattr(config, '_FULL_CONFIG', {'users': {'test': {'directories': ['/capture']}}})
    seed_photos_prefix('/hidden/', [dict(path='/hidden/a.jpg', filename='a.jpg', date_taken='2024:01:01 00:00:00')])
    target = dict(filters={}) if filtered else dict(photo_paths=[*paths, paths[0], '/hidden/a.jpg', '/missing'])
    body = dict(**target, exclude=[paths[1]], offset_seconds=60)
    result = edition_client.post('/api/photos/capture_date/preview', json=body)
    assert result.status_code == 200
    data = result.json()
    assert data['changed'] == 2
    assert [s['path'] for s in data['samples']] == [paths[0], paths[2]]
    config._FULL_CONFIG['users']['test']['directories'] = []
    assert edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': data['preview_token']}).status_code == 409
    assert values(paths) == [('2024:01:01 00:00:00', 0)] * 3


def test_filter_target_limit_and_bounded_samples(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'] * 1001)
    body = dict(filters={'path': '/capture/'}, offset_seconds=60)
    # Scope by an existing exact path-prefix filter through the gallery parser.
    body['filters'] = {'folder': '/capture'}
    assert edition_client.post('/api/photos/capture_date/preview', json=body).status_code == 422
    body['exclude'] = [paths[-1]]
    response = edition_client.post('/api/photos/capture_date/preview', json=body)
    assert response.status_code == 200
    assert response.json()['changed'] == 1000
    assert len(response.json()['samples']) == 20


def test_apply_rolls_back_all_rows_on_database_failure(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'] * 2)
    body = dict(photo_paths=paths, offset_seconds=60)
    preview = edition_client.post('/api/photos/capture_date/preview', json=body).json()
    with get_db() as conn, conn:
        conn.execute("CREATE TRIGGER capture_fail BEFORE UPDATE OF date_taken ON photos WHEN NEW.path='/capture/1.jpg' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    try:
        with pytest.raises(Exception, match='test failure'):
            edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': preview['preview_token']})
        assert values(paths) == [('2024:01:01 00:00:00', 0)] * 2
    finally:
        with get_db() as conn, conn:
            conn.execute('DROP TRIGGER capture_fail')


def test_preview_does_not_take_write_lock(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'])
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            assert edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=paths, offset_seconds=1)).status_code == 200
        finally:
            conn.rollback()


def test_explicit_export_preserves_original_until_embed(tmp_path):
    import json
    import shutil
    import subprocess
    from PIL import Image
    from processing.xmp_export import XmpRating, write_metadata
    exe = shutil.which('exiftool')
    if not exe:
        pytest.skip('ExifTool is unavailable')
    image = tmp_path / 'date.jpg'
    Image.new('RGB', (12, 12), 'blue').save(image)
    subprocess.run([exe, '-overwrite_original', '-EXIF:DateTimeOriginal=2000:01:01 00:00:00', '-EXIF:CreateDate=2001:01:01 00:00:00', '-EXIF:OffsetTimeOriginal=+02:00', '-EXIF:SubSecTimeOriginal=123', str(image)], check=True, capture_output=True)
    before = image.read_bytes()
    rating = XmpRating.from_row(dict(date_taken='2024:02:29 01:02:03', date_manually_set=1))
    write_metadata(str(image), rating)
    assert image.read_bytes() == before
    write_metadata(str(image), rating, embed_original=True)
    result = json.loads(subprocess.check_output([exe, '-json', '-EXIF:DateTimeOriginal', '-EXIF:CreateDate', '-EXIF:OffsetTimeOriginal', '-EXIF:SubSecTimeOriginal', '-XMP-exif:DateTimeOriginal', '-G1', str(image)]))[0]
    assert result['ExifIFD:DateTimeOriginal'] == '2024:02:29 01:02:03'
    assert result['XMP-exif:DateTimeOriginal'] == '2024:02:29 01:02:03'
    assert result['ExifIFD:CreateDate'] == '2001:01:01 00:00:00'
    assert result['ExifIFD:OffsetTimeOriginal'] == '+02:00'
    assert str(result['ExifIFD:SubSecTimeOriginal']) == '123'


def test_photo_contract_carries_manual_date(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'])
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET date_manually_set=1 WHERE path=?', (paths[0],))
    response = edition_client.get('/api/photo', params={'path': paths[0]})
    assert response.status_code == 200
    assert response.json()['date_manually_set'] == 1
