"""Capture walltime correction: bounded preview, atomic apply, strict dates."""
import sqlite3
from unittest.mock import patch
from pathlib import Path

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



def test_apply_keeps_durable_stats_cache_state(edition_client, seed_photos_prefix):
    import time
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'])
    with get_db() as conn, conn:
        conn.executemany('INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)',
                         [('keeper_head:test', 'weights', time.time()), ('scenes_test', 'derived', time.time())])
    body = dict(photo_paths=paths, offset_seconds=60)
    token = edition_client.post('/api/photos/capture_date/preview', json=body).json()['preview_token']
    assert edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': token}).status_code == 200
    with get_db() as conn:
        kept = {row[0] for row in conn.execute("SELECT key FROM stats_cache WHERE key IN ('keeper_head:test', 'scenes_test')")}
    with get_db() as conn, conn:
        conn.execute("DELETE FROM stats_cache WHERE key = 'keeper_head:test'")
    assert kept == {'keeper_head:test'}

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


@pytest.mark.parametrize('partial,manual', [(False, False), (False, True), (True, True)])
def test_rescan_preserves_manual_date_pair(tmp_path, partial, manual):
    import sqlite3
    from db.schema import init_database
    from processing.scorer import _PARTIAL_CORE_COLUMNS, _photos_partial_upsert, _photos_upsert
    db = str(tmp_path / 'dates.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photos(path, date_taken, date_manually_set) VALUES ('p','2024:01:01 01:02:03',?)", (int(manual),))
        if partial:
            sql = _photos_partial_upsert(('date_manually_set',))
            params = {key: None for key in _PARTIAL_CORE_COLUMNS}
            params.update(path='p', date_taken='2000:01:01 01:02:03', date_manually_set=0)
        else:
            sql = _photos_upsert('INSERT OR REPLACE INTO photos(path,date_taken,date_manually_set) VALUES (?,?,?)')
            params = ('p', '2000:01:01 01:02:03', 0)
        conn.execute(sql, params)
        expected = ('2024:01:01 01:02:03', 1) if manual else ('2000:01:01 01:02:03', 0)
        assert conn.execute('SELECT date_taken,date_manually_set FROM photos').fetchone() == expected


def test_manual_date_export_only():
    from processing.xmp_export import XmpRating, build_xmp, _exiftool_tag_args
    manual = XmpRating.from_row(dict(date_taken='2024:01:01 01:02:03', date_manually_set=1))
    assert 'exif:DateTimeOriginal="2024-01-01T01:02:03"' in build_xmp(manual)
    assert '-XMP-exif:DateTimeOriginal=2024-01-01T01:02:03' in _exiftool_tag_args(manual, [], [])
    scanned = XmpRating.from_row(dict(date_taken='2024:01:01 01:02:03'))
    assert 'DateTimeOriginal' not in build_xmp(scanned)
    assert not any('DateTimeOriginal' in arg for arg in _exiftool_tag_args(scanned, [], []))


@pytest.mark.parametrize('date', ['2024:01:01', 'garbage', None])
def test_manual_date_refuses_a_partial_walltime(date):
    from processing.xmp_export import XmpRating
    with pytest.raises(ValueError):
        XmpRating.from_row(dict(date_taken=date, date_manually_set=1)).manual_date()


@pytest.mark.parametrize('metadata,status', [({}, 404), ('2024:01:01', 409)])
def test_reset_keeps_manual_date_when_file_date_unusable(edition_client, seed_photos_prefix, tmp_path, metadata, status):
    paths = seed(seed_photos_prefix, ['2024:01:01 01:02:03'])
    disk = tmp_path / 'a.jpg'
    disk.write_bytes(b'original')
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET date_manually_set=1 WHERE path=?', (paths[0],))
    exif = metadata if isinstance(metadata, dict) else {str(disk): {'date_taken': metadata}}
    with patch('api.routers.capture_dates.resolve_photo_disk_path', return_value=str(disk)), patch('api.routers.capture_dates.get_exif_batch', return_value=exif):
        result = edition_client.delete('/api/photo/capture_date', params={'path': paths[0]})
    assert result.status_code == status
    assert values(paths) == [('2024:01:01 01:02:03', 1)]


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
        with pytest.raises(sqlite3.IntegrityError, match='test failure'):
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
    sidecar = write_metadata(str(image), rating)['sidecar']
    assert image.read_bytes() == before
    packet = json.loads(subprocess.check_output(
        [exe, '-json', '-XMP-exif:DateTimeOriginal', '-G1', sidecar], encoding='utf-8'))[0]
    assert packet['XMP-exif:DateTimeOriginal'] == '2024:02:29 01:02:03'
    write_metadata(str(image), rating, embed_original=True)
    result = json.loads(subprocess.check_output([exe, '-json', '-EXIF:DateTimeOriginal', '-EXIF:CreateDate', '-EXIF:OffsetTimeOriginal', '-EXIF:SubSecTimeOriginal', '-XMP-exif:DateTimeOriginal', '-G1', str(image)]))[0]
    assert result['ExifIFD:DateTimeOriginal'] == '2024:02:29 01:02:03'
    assert result['XMP-exif:DateTimeOriginal'] == '2024:02:29 01:02:03'
    assert result['ExifIFD:CreateDate'] == '2001:01:01 00:00:00'
    assert result['ExifIFD:OffsetTimeOriginal'] == '+02:00'
    assert str(result['ExifIFD:SubSecTimeOriginal']) == '123'


@pytest.mark.parametrize('foreign', [False, True])
def test_reset_export_clears_only_facets_sidecar_date(tmp_path, foreign):
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
    if foreign:
        sidecar = write_metadata(str(image), XmpRating())['sidecar']
        subprocess.run([exe, '-overwrite_original', '-XMP-exif:DateTimeOriginal=2010:05:05 05:05:05', sidecar], check=True, capture_output=True)
    else:
        sidecar = write_metadata(str(image), XmpRating.from_row(dict(date_taken='2024:02:29 01:02:03', date_manually_set=1)))['sidecar']
    write_metadata(str(image), XmpRating.from_row(dict(date_taken='2000:01:01 00:00:00')))
    result = json.loads(subprocess.check_output([exe, '-json', '-XMP-exif:DateTimeOriginal', '-G1', sidecar]))[0]
    assert result.get('XMP-exif:DateTimeOriginal') == ('2010:05:05 05:05:05' if foreign else None)


def test_photo_contract_carries_manual_date(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'])
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET date_manually_set=1 WHERE path=?', (paths[0],))
    response = edition_client.get('/api/photo', params={'path': paths[0]})
    assert response.status_code == 200
    assert response.json()['date_manually_set'] == 1


@pytest.fixture
def reset_photo(edition_client, seed_photos_prefix, tmp_path, monkeypatch):
    from api.routers import capture_dates

    image = tmp_path / 'reset.jpg'
    image.write_bytes(b'original')
    path = str(image)
    seed_photos_prefix(str(tmp_path), [dict(path=path, filename=image.name,
                                          date_taken='2024:01:01 01:02:03', date_manually_set=1)])
    monkeypatch.setattr(capture_dates, 'get_exif_batch',
                        lambda paths: {path: {'date_taken': '2000:01:01 00:00:00'}})
    return path


@pytest.mark.parametrize('release_on_busy', [True, False])
def test_reset_retries_real_writer_contention(edition_client, reset_photo, monkeypatch, release_on_busy):
    import sqlite3
    from contextlib import contextmanager
    from api import database
    from api.db_helpers import RETRY_ATTEMPTS, LIBRARY_BUSY_DETAIL
    from api.routers import capture_dates

    blocker = sqlite3.connect(database.DEFAULT_DB_PATH, check_same_thread=False)
    attempts = []

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            try:
                return super().execute(sql, parameters)
            except sqlite3.OperationalError:
                if sql == 'BEGIN IMMEDIATE':
                    attempts.append(sql)
                    if release_on_busy:
                        blocker.rollback()
                raise

    @contextmanager
    def database_without_busy_wait():
        conn = sqlite3.connect(database.DEFAULT_DB_PATH, timeout=0, factory=ObservedConnection)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(capture_dates, 'get_db', database_without_busy_wait)
    blocker.execute('BEGIN IMMEDIATE')
    try:
        response = edition_client.delete('/api/photo/capture_date', params={'path': reset_photo})
        if release_on_busy:
            assert response.status_code == 200, response.text
            assert len(attempts) == 1
            assert response.json() == dict(date_taken='2000:01:01 00:00:00', date_manually_set=0)
        else:
            assert response.status_code == 503, response.text
            assert response.json() == {'detail': LIBRARY_BUSY_DETAIL}
            assert 'Retry-After' in response.headers
            assert len(attempts) == RETRY_ATTEMPTS
    finally:
        blocker.rollback()
        blocker.close()
    expected = ('2000:01:01 00:00:00', 0) if release_on_busy else ('2024:01:01 01:02:03', 1)
    assert values([reset_photo]) == [expected]
    assert Path(reset_photo).read_bytes() == b'original'


def test_reset_database_failure_rolls_back_override_and_history(edition_client, reset_photo):
    with get_db() as conn, conn:
        history_before = conn.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0]
        conn.execute("CREATE TRIGGER capture_reset_fail BEFORE INSERT ON organization_history BEGIN SELECT RAISE(ABORT, 'private /server/library/date.db'); END")
    try:
        response = edition_client.delete('/api/photo/capture_date', params={'path': reset_photo})
        assert response.status_code == 500
        assert response.json() == {'detail': 'Internal server error'}
        assert '/server/library' not in response.text
        assert values([reset_photo]) == [('2024:01:01 01:02:03', 1)]
        with get_db() as conn:
            assert conn.execute('SELECT COUNT(*) FROM organization_history').fetchone()[0] == history_before
        assert Path(reset_photo).read_bytes() == b'original'
    finally:
        with get_db() as conn, conn:
            conn.execute('DROP TRIGGER capture_reset_fail')


def test_set_date_dates_only_the_rows_without_a_usable_date(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, [None, '2024-01-01', '2024:01:01 00:00:00', '2024:05:06 07:08:09'])
    body = dict(photo_paths=paths, set_date='2024-05-06T07:08:09')
    data = edition_client.post('/api/photos/capture_date/preview', json=body).json()
    assert (data['changed'], data['skipped']) == (2, 2)
    assert data['samples'] == [dict(path=paths[0], old_date=None, new_date='2024:05:06 07:08:09'),
                               dict(path=paths[1], old_date='2024-01-01', new_date='2024:05:06 07:08:09')]
    assert values(paths)[0] == (None, 0)
    assert edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': data['preview_token']}).status_code == 200
    assert values(paths) == [('2024:05:06 07:08:09', 1), ('2024:05:06 07:08:09', 1),
                             ('2024:01:01 00:00:00', 0), ('2024:05:06 07:08:09', 0)]


def test_set_date_over_a_filter_scope_keeps_every_dated_photo(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, [None, '2023:03:04 05:06:07', '2021:01:01 12:00:00'])
    body = dict(filters={'folder': '/capture'}, set_date='2024-05-06T07:08:09')
    data = edition_client.post('/api/photos/capture_date/preview', json=body).json()
    assert (data['changed'], data['skipped']) == (1, 2)
    assert edition_client.post('/api/photos/capture_date/apply', json={**body, 'preview_token': data['preview_token']}).status_code == 200
    assert values(paths) == [('2024:05:06 07:08:09', 1), ('2023:03:04 05:06:07', 0), ('2021:01:01 12:00:00', 0)]


@pytest.mark.parametrize('extra', [{}, dict(offset_seconds=5, set_date='2024-05-06T07:08:09')])
def test_exactly_one_of_offset_or_set_date(edition_client, extra):
    assert edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=[], **extra)).status_code == 422


@pytest.mark.parametrize('date', ['', 'garbage', '2024-02-30T12:00:00', '2024-05-06', '2024-05-06T07:08:09Z', 5])
def test_unparseable_set_date(edition_client, date):
    assert edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=[], set_date=date)).status_code == 422


def test_set_date_accepts_stored_and_space_forms(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, [None])
    for form in ('2024:05:06 07:08:09', '2024-05-06 07:08:09'):
        data = edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=paths, set_date=form)).json()
        assert data['samples'][0]['new_date'] == '2024:05:06 07:08:09'


def test_token_is_bound_to_the_mode_and_value(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, ['2024:01:01 00:00:00'])
    offset_token = edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=paths, offset_seconds=60)).json()['preview_token']
    set_body = dict(photo_paths=paths, set_date='2024-01-01T00:01:00')
    set_token = edition_client.post('/api/photos/capture_date/preview', json=set_body).json()['preview_token']
    assert offset_token != set_token
    assert edition_client.post('/api/photos/capture_date/apply', json={**set_body, 'preview_token': offset_token}).status_code == 409
    assert edition_client.post('/api/photos/capture_date/apply', json=dict(photo_paths=paths, offset_seconds=60, preview_token=set_token)).status_code == 409
    other = edition_client.post('/api/photos/capture_date/apply', json={**set_body, 'set_date': '2024-01-01T00:02:00', 'preview_token': set_token})
    assert other.status_code == 409
    assert values(paths) == [('2024:01:01 00:00:00', 0)]


def test_offset_requests_still_skip_undated_rows(edition_client, seed_photos_prefix):
    paths = seed(seed_photos_prefix, [None])
    data = edition_client.post('/api/photos/capture_date/preview', json=dict(photo_paths=paths, offset_seconds=60)).json()
    assert (data['changed'], data['skipped'], data['samples']) == (0, 1, [])
