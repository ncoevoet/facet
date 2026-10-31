"""Real lock/receipt tests; cancellation never interrupts a file write."""
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time

import pytest

from api import sidecar_jobs as jobs
from db.schema import init_database
from facet import LibraryLockError, library_job_holder
from tests._sidecar_helpers import settle_sidecar_job


@pytest.fixture
def library(tmp_path):
    path = str(tmp_path / 'library.db')
    init_database(path)
    return path


def _done(library, job_id, owner='alice'):
    return settle_sidecar_job(library, job_id, owner)


def test_one_active_library_job_and_cancel_between_files(library):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def work(path):
        calls.append(path)
        entered.set()
        assert release.wait(5)
        return {'written': 1, 'skipped': 0, 'errors': 0}
    state = jobs.start(library, 'alice', ['first', 'second'], work)
    try:
        assert entered.wait(3)
        assert state['total'] == 2
        with pytest.raises(LibraryLockError):
            jobs.start(library, 'alice', ['other'], work)
        assert jobs.cancel(library, state['id'], 'alice')['cancel_requested']
        # Cancellation has not torn a file write in half.
        assert calls == ['first']
    finally:
        release.set()
    result = _done(library, state['id'])
    assert result['state'] == 'cancelled'
    assert result['processed'] == result['written'] == 1
    assert calls == ['first']
    assert 'owner' not in result


def test_worker_crash_reports_the_stopped_error_code(library):
    def work(path):
        raise RuntimeError('secret /private/path')
    state = jobs.start(library, 'alice', ['first'], work)
    result = _done(library, state['id'])
    assert result['state'] == 'failed'
    assert result['first_error_code'] == 'stopped'
    assert 'secret' not in result['first_error']


def test_receipts_are_private_and_path_ids_cannot_escape(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    with pytest.raises(LookupError):
        jobs.status(library, state['id'], 'bob')
    with pytest.raises(LookupError):
        jobs.cancel(library, state['id'], 'bob')
    with pytest.raises(LookupError):
        jobs.status(library, '../../secret', 'alice')


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX permission bits do not apply on Windows')
def test_receipts_are_owner_only(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    assert jobs._path(library, state['id']).stat().st_mode & 0o077 == 0


def test_failed_worker_releases_lock_and_retains_confirmed_counts(library):
    def work(path):
        if path == 'second':
            raise OSError('do not expose this secret')
        return {'written': 0, 'skipped': 0, 'errors': 1, 'first_error': 'metadata failed'}
    state = jobs.start(library, 'alice', ['first', 'second'], work)
    result = _done(library, state['id'])
    assert result['state'] == 'failed'
    assert result['processed'] == result['errors'] == 1
    assert 'secret' not in result['first_error']
    other = jobs.start(library, 'alice', [], lambda path: None)
    assert _done(library, other['id'])['state'] == 'completed'


def test_dead_receipt_is_interrupted_without_trusting_a_recycled_pid(library):
    from uuid import uuid4
    job_id = str(uuid4())
    path = jobs._path(library, job_id)
    state = {'id': job_id, 'owner': 'alice', 'state': 'running', 'started_at': 0,
             'total': 3, 'processed': 1, 'written': 1, 'skipped': 0, 'errors': 0,
             'first_error': None, 'retry': []}
    jobs._write(path, state)
    assert jobs.status(library, job_id, 'alice')['state'] == 'interrupted'
    assert jobs._read(path) == state  # poll cannot race-write over a terminal receipt


def _poll_during(library, job_id, disturb):
    """Run ``status`` on a thread while ``disturb`` makes the receipt unreadable."""
    outcome = []

    def poll():
        try:
            outcome.append(jobs.status(library, job_id, 'alice'))
        except BaseException as ex:
            outcome.append(ex)

    poller = threading.Thread(target=poll)
    disturb(poller)
    poller.join(5)
    assert not poller.is_alive()
    return outcome[0]


@pytest.fixture
def finished_job(library):
    from uuid import uuid4
    job_id = str(uuid4())
    path = jobs._path(library, job_id)
    jobs._write(path, {'id': job_id, 'owner': 'alice', 'state': 'completed', 'started_at': 0,
                       'total': 1, 'processed': 1, 'written': 1, 'skipped': 0, 'errors': 0,
                       'first_error': None, 'retry': []})
    return job_id, path


@pytest.mark.skipif(sys.platform != 'win32', reason='receipt retry exists on Windows only')
def test_status_survives_the_receipt_being_republished(library, finished_job):
    job_id, path = finished_job
    saved = path.read_bytes()

    def republish_after_a_gap(poller):
        path.unlink()
        poller.start()
        time.sleep(0.02)
        path.write_bytes(saved)

    result = _poll_during(library, job_id, republish_after_a_gap)
    assert not isinstance(result, BaseException), result
    assert result['id'] == job_id


@pytest.mark.skipif(sys.platform != 'win32', reason='receipt retry exists on Windows only')
def test_status_survives_the_receipt_being_briefly_held_exclusively(library, finished_job):
    import ctypes
    from ctypes import wintypes

    job_id, path = finished_job
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # GENERIC_READ with share mode 0: every other open, ReadFile's own included, is refused.
    held = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    assert held != wintypes.HANDLE(-1).value

    def release_after_a_gap(poller):
        try:
            poller.start()
            time.sleep(0.02)
        finally:
            kernel.CloseHandle(held)

    result = _poll_during(library, job_id, release_after_a_gap)
    assert not isinstance(result, BaseException), result
    assert result['id'] == job_id


def test_prune_retains_twenty_receipts_and_other_principals(library):
    from uuid import uuid4
    for owner in ('alice', 'bob'):
        for index in range(25):
            job_id = str(uuid4())
            jobs._write(jobs._path(library, job_id), {
                'id': job_id, 'owner': owner, 'state': 'running', 'started_at': index,
                'total': 0, 'processed': 0, 'written': 0, 'skipped': 0, 'errors': 0, 'retry': []})
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    receipts = [jobs._read(p) for p in jobs._directory(library).glob('*.json')]
    assert sum(r['owner'] == 'alice' for r in receipts) == 20
    assert sum(r['owner'] == 'bob' for r in receipts) == 25


def test_start_failure_releases_library_admission(library, monkeypatch):
    def fail(*args):
        raise OSError('no space')
    monkeypatch.setattr(jobs, '_write', fail)
    with pytest.raises(OSError):
        jobs.start(library, 'alice', [], lambda path: None)
    assert library_job_holder(library) is None


def test_api_returns_before_export_completes_and_rechecks_visibility(edition_client, tmp_path, seed_photos_prefix, monkeypatch):
    from api import config
    from api.routers import export
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    paths = [str(tmp_path / name) for name in ('one.jpg', 'two.jpg')]
    for path in paths:
        Path(path).write_bytes(b'temporary test media')
    seed_photos_prefix(str(tmp_path), [{'path': path, 'filename': Path(path).name} for path in paths])
    entered, release = threading.Event(), threading.Event()
    calls = []
    def write(path, *args, **kwargs):
        calls.append(path)
        entered.set()
        assert release.wait(5)
        return {'sidecar': path + '.xmp'}
    monkeypatch.setattr(export, 'write_metadata', write)
    response = edition_client.post('/api/export/sidecar_jobs', json={'paths': paths})
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    try:
        assert entered.wait(3)
        response = edition_client.get(f'/api/export/sidecar_jobs/{job_id}')
        assert response.json()['processed'] == 0
        assert edition_client.post('/api/export/sidecar_jobs', json={'paths': paths}).status_code == 503
        # Revocation of filesystem scope prevents the next file write.
        monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path / 'other')])
    finally:
        release.set()
    from api.database import DEFAULT_DB_PATH
    owner = jobs._read(jobs._path(DEFAULT_DB_PATH, job_id))['owner']
    result = _done(DEFAULT_DB_PATH, job_id, owner)
    assert result['written'] == result['skipped'] == 1
    assert result['processed'] == 2
    assert calls == [paths[0]]


def test_retry_plan_contains_failures_skips_and_unprocessed_tail(library):
    entered, release = threading.Event(), threading.Event()
    def work(path):
        if path == 'first':
            return {'written': 0, 'skipped': 0, 'errors': 1}
        entered.set()
        assert release.wait(5)
        return {'written': 1, 'skipped': 0, 'errors': 0}
    state = jobs.start(library, 'alice', ['first', 'second', 'third'], work, overwrite=True)
    try:
        assert entered.wait(3)
        with pytest.raises(ValueError, match='still running'):
            jobs.remaining(library, state['id'], 'alice')
        jobs.cancel(library, state['id'], 'alice')
    finally:
        release.set()
    _done(library, state['id'])
    assert jobs.remaining(library, state['id'], 'alice') == (['first', 'third'], True)
    assert [r['id'] for r in jobs.recent(library, 'alice')] == [state['id']]
    assert jobs.recent(library, 'bob') == []
    with pytest.raises(LookupError):
        jobs.remaining(library, state['id'], 'bob')


def test_interrupted_receipt_retries_unknown_file_explicitly(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    old = jobs._read(path)
    old.update(state='running', total=2, processed=1, written=1)
    jobs._write(path, old)
    jobs._write(path.with_suffix('.plan'), {'owner': 'alice', 'paths': ['done', 'unknown'], 'overwrite': False})
    assert jobs.remaining(library, state['id'], 'alice') == (['unknown'], False)


def test_corrupt_receipt_does_not_break_recent_job_recovery(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    malformed = jobs._read(path)
    malformed['processed'] = 1  # total remains zero
    jobs._write(path, malformed)
    with pytest.raises(LookupError):
        jobs.status(library, state['id'], 'alice')
    assert jobs.recent(library, 'alice') == []


@pytest.mark.parametrize('cleanup_failure', ['plan', 'lock'])
def test_admission_cleanup_failure_cannot_hang_caller(library, monkeypatch, cleanup_failure):
    import facet
    original_write = jobs._write
    def write(path, state):
        if path.suffix == '.json':
            raise OSError('receipt write failed')
        return original_write(path, state)
    monkeypatch.setattr(jobs, '_write', write)
    if cleanup_failure == 'plan':
        unlink = Path.unlink
        def refuse_plan(path, *args, **kwargs):
            if path.suffix == '.plan':
                raise PermissionError('cleanup refused')
            return unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'unlink', refuse_plan)
    else:
        release = facet.LibraryLock.release
        def fail_release(lock):
            release(lock)
            raise OSError('release cleanup failed')
        monkeypatch.setattr(facet.LibraryLock, 'release', fail_release)
    settled = threading.Event()
    failures = []
    def call():
        try:
            jobs.start(library, 'alice', [], lambda path: None)
        except Exception as ex:
            failures.append(ex)
        finally:
            settled.set()
    caller = threading.Thread(target=call, daemon=True)
    caller.start()
    assert settled.wait(3), 'admission cleanup left the caller blocked'
    caller.join(1)
    assert len(failures) == 1 and 'receipt write failed' in str(failures[0])
    assert library_job_holder(library) is None


def test_retry_rereads_confirmed_progress_after_completion_race(library, monkeypatch):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    old = jobs._read(path)
    old.update(state='running', total=1)
    jobs._write(path, old)
    jobs._write(path.with_suffix('.plan'), {'owner': 'alice', 'paths': ['done'], 'overwrite': False})
    status = jobs.status
    def complete_then_status(*args):
        current = jobs._read(path)
        current.update(state='completed', processed=1, written=1)
        jobs._write(path, current)
        return status(*args)
    monkeypatch.setattr(jobs, 'status', complete_then_status)
    assert jobs.remaining(library, state['id'], 'alice') == ([], False)


@pytest.mark.parametrize('bad_timestamp', ['not-a-time', None, float('nan')])
def test_malformed_timestamp_does_not_block_history_or_new_admission(library, bad_timestamp):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    corrupt = jobs._read(path)
    corrupt['started_at'] = bad_timestamp
    jobs._write(path, corrupt)
    assert jobs.recent(library, 'alice') == []
    another = jobs.start(library, 'alice', [], lambda path: None)
    assert _done(library, another['id'])['state'] == 'completed'
    assert len(jobs.recent(library, 'alice')) == 1


def test_numeric_string_progress_is_not_used_for_retry_arithmetic(library):
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    malformed = jobs._read(path)
    malformed['processed'] = '0'  # Public response coercion must not validate private arithmetic.
    jobs._write(path, malformed)
    with pytest.raises(LookupError):
        jobs.remaining(library, state['id'], 'alice')
    assert jobs.recent(library, 'alice') == []
    another = jobs.start(library, 'alice', [], lambda path: None)
    assert _done(library, another['id'])['state'] == 'completed'


@pytest.mark.parametrize('bad_id', [{}, 'not-a-uuid', None])
def test_invalid_receipt_id_is_skipped_before_history_tiebreak(library, bad_id):
    from uuid import uuid4
    healthy = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, healthy['id'])
    valid = jobs._read(jobs._path(library, healthy['id']))
    invalid_path = jobs._path(library, str(uuid4()))
    jobs._write(invalid_path, {**valid, 'id': bad_id})  # Same timestamp exercises the sort tie.
    assert [row['id'] for row in jobs.recent(library, 'alice')] == [healthy['id']]
    with pytest.raises(LookupError):
        jobs.status(library, invalid_path.stem, 'alice')


def test_receipt_identity_must_match_the_requested_filename(library):
    from uuid import uuid4
    state = jobs.start(library, 'alice', [], lambda path: None)
    _done(library, state['id'])
    path = jobs._path(library, state['id'])
    malformed = jobs._read(path)
    malformed['id'] = str(uuid4())
    jobs._write(path, malformed)
    with pytest.raises(LookupError):
        jobs.status(library, state['id'], 'alice')


@pytest.mark.parametrize('bad_retry', [[2], [-1], ['0'], [True], [0, 0], []])
def test_invalid_private_retry_indices_are_refused(library, bad_retry):
    def failed(path):
        return {'written': 0, 'skipped': 0, 'errors': 1}
    state = jobs.start(library, 'alice', ['failed'], failed)
    _done(library, state['id'])
    assert jobs.remaining(library, state['id'], 'alice') == (['failed'], False)
    path = jobs._path(library, state['id'])
    malformed = jobs._read(path)
    malformed['retry'] = bad_retry
    jobs._write(path, malformed)
    with pytest.raises(LookupError):
        jobs.remaining(library, state['id'], 'alice')


@pytest.mark.parametrize('change', [
    {'paths': 'not-a-list'}, {'paths': [1]}, {'paths': []}, {'overwrite': 'false'}, {'owner': 'bob'},
])
def test_retry_validates_plan_shape_and_receipt_length(library, change):
    def failed(path):
        return {'written': 0, 'skipped': 0, 'errors': 1}
    state = jobs.start(library, 'alice', ['failed'], failed, overwrite=True)
    _done(library, state['id'])
    plan_path = jobs._path(library, state['id']).with_suffix('.plan')
    plan = jobs._read(plan_path)
    jobs._write(plan_path, {**plan, **change})
    with pytest.raises(LookupError):
        jobs.remaining(library, state['id'], 'alice')


def test_api_returns_not_found_for_invalid_private_retry_record(edition_client):
    from api.database import DEFAULT_DB_PATH
    response = edition_client.post('/api/export/sidecar_jobs', json={'paths': ['/unregistered-job-fixture.jpg']})
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    path = jobs._path(DEFAULT_DB_PATH, job_id)
    owner = jobs._read(path)['owner']
    _done(DEFAULT_DB_PATH, job_id, owner)
    state = jobs._read(path)
    state.update(state='completed', total=1, processed=1, written=0, skipped=0, errors=1, retry=[2])
    jobs._write(path, state)
    response = edition_client.post(f'/api/export/sidecar_jobs/{job_id}/retry')
    assert response.status_code == 404, response.text


def test_api_does_not_report_an_unrelated_lookup_bug_as_a_missing_job(edition_client, monkeypatch):
    """Only an unknown job is a 404; a KeyError while selecting paths is a server error."""
    from fastapi.testclient import TestClient
    from api.routers import export

    def broken_selection(*args, **kwargs):
        raise KeyError('row column')

    monkeypatch.setattr(export, '_selected_paths', broken_selection)
    client = TestClient(edition_client.app, raise_server_exceptions=False)
    response = client.post('/api/export/sidecar_jobs', json={'paths': ['/unregistered-job-fixture.jpg']})
    assert response.status_code == 500, response.text
    assert 'Export job not found' not in response.text


@pytest.mark.parametrize('operation', ['start', 'retry'])
@pytest.mark.parametrize('unusable', [False, True])
def test_api_distinguishes_unusable_lock_from_busy(edition_client, monkeypatch, operation, unusable):
    from facet import LibraryLockUnusableError
    if operation == 'retry':
        monkeypatch.setattr(jobs, 'remaining', lambda *args: (['/unregistered-job-fixture.jpg'], False))
    def refuse(*args, **kwargs):
        error = LibraryLockUnusableError if unusable else LibraryLockError
        raise error('private-cache-path must not leak')
    monkeypatch.setattr(jobs, 'start', refuse)
    route = '/api/export/sidecar_jobs' + ('/job/retry' if operation == 'retry' else '')
    response = edition_client.post(route, json={'paths': ['/unregistered-job-fixture.jpg']})
    assert response.status_code == 503, response.text
    assert ('lock is unavailable' if unusable else 'library_busy') in response.json()['detail'].lower()
    assert ('Retry-After' in response.headers) is not unusable
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'private-cache-path' not in response.text


def test_album_job_over_real_10000_cap_is_refused_before_admission(edition_client, seed_photos_prefix, monkeypatch):
    from api.database import get_db
    prefix = '/job-album-cap/'
    rows = [{'path': f'{prefix}{index}.jpg', 'filename': f'{index}.jpg'} for index in range(10001)]
    seed_photos_prefix(prefix, rows)
    with get_db() as conn:
        album_id = conn.execute("INSERT INTO albums (name) VALUES ('job cap fixture')").lastrowid
        conn.executemany('INSERT INTO album_photos (album_id, photo_path) VALUES (?, ?)',
                         [(album_id, row['path']) for row in rows])
        conn.commit()
    def unexpected_admission(*args, **kwargs):
        pytest.fail('Oversized album must be refused before job admission')
    monkeypatch.setattr(jobs, 'start', unexpected_admission)
    try:
        response = edition_client.post('/api/export/sidecar_jobs', json={'filters': {'album_id': str(album_id)}})
        assert response.status_code == 412, response.text
        assert '10001' in response.json()['detail'] and '10000' in response.json()['detail']
    finally:
        with get_db() as conn:
            conn.execute('DELETE FROM albums WHERE id=?', (album_id,))
            conn.commit()


def test_smart_album_job_preserves_stored_membership_contract(edition_client, tmp_path, seed_photos_prefix, monkeypatch):
    import json
    from api import config
    from api.database import DEFAULT_DB_PATH, get_db
    from api.routers import export
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    paths = [str(tmp_path / name) for name in ('current.jpg', 'stale.jpg')]
    for path in paths:
        Path(path).write_bytes(b'test media')
    seed_photos_prefix(str(tmp_path), [
        {'path': paths[0], 'filename': 'current.jpg', 'category': 'job-live-filter'},
        {'path': paths[1], 'filename': 'stale.jpg', 'category': 'other'},
    ])
    with get_db() as conn:
        album_id = conn.execute('INSERT INTO albums (name, is_smart, smart_filter_json) VALUES (?, 1, ?)',
                                ('job live fixture', json.dumps({'category': 'job-live-filter'}))).lastrowid
        conn.execute('INSERT INTO album_photos (album_id, photo_path) VALUES (?, ?)', (album_id, paths[1]))
        conn.commit()
    calls = []
    def write(path, *args, **kwargs):
        calls.append(path)
        return {'sidecar': path + '.xmp'}
    monkeypatch.setattr(export, 'write_metadata', write)
    try:
        response = edition_client.post('/api/export/sidecar_jobs', json={'filters': {'album_id': str(album_id)}})
        assert response.status_code == 202, response.text
        job_id = response.json()['id']
        owner = jobs._read(jobs._path(DEFAULT_DB_PATH, job_id))['owner']
        result = _done(DEFAULT_DB_PATH, job_id, owner)
        assert result['total'] == result['written'] == 1
        assert calls == [paths[1]]
    finally:
        with get_db() as conn:
            conn.execute('DELETE FROM albums WHERE id=?', (album_id,))
            conn.commit()


@pytest.mark.skipif(shutil.which('exiftool') is None, reason='requires ExifTool')
def test_background_export_preserves_foreign_keywords_and_ai_manual_provenance(edition_client, tmp_path, seed_photos_prefix, monkeypatch):
    """The asynchronous worker must carry the same keyword authority as direct exports."""
    from PIL import Image
    from xml.etree import ElementTree as ET
    from api import config
    from api.database import DEFAULT_DB_PATH
    from processing import xmp_export as xe
    from processing.xmp_import import parse_sidecar

    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    image = tmp_path / 'provenance.jpg'
    Image.new('RGB', (40, 30), 'blue').save(image)
    path = str(image)
    seed_photos_prefix(str(tmp_path), [{'path': path, 'filename': image.name, 'tags': 'machine,shared'}])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.executemany("INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES (?,?,'user')",
                         [(path, 'manual'), (path, 'shared')])
    # An external keyword has no Facet ownership marker.
    packet = ET.fromstring(xe.build_xmp(xe.XmpRating(tags=['foreign'])))
    description = packet.find(f'.//{{{xe.NS_RDF}}}Description')
    assert description is not None
    description.attrib.pop(f'{{{xe.NS_FACET}}}KeywordState')
    sidecar = Path(path + '.xmp')
    sidecar.write_bytes(ET.tostring(packet, encoding='utf-8'))
    original = image.read_bytes()

    response = edition_client.post('/api/export/sidecar_jobs', json={'paths': [path]})
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    owner = jobs._read(jobs._path(DEFAULT_DB_PATH, job_id))['owner']
    result = _done(DEFAULT_DB_PATH, job_id, owner)
    assert result['state'] == 'completed'
    assert result['processed'] == result['written'] == 1
    assert result['errors'] == result['skipped'] == 0
    parsed = parse_sidecar(str(sidecar))
    assert parsed['keyword_state']['ai'] == ['machine', 'shared']
    assert parsed['keyword_state']['manual'] == ['manual', 'shared']
    assert 'foreign' in parsed['tags']
    assert image.read_bytes() == original


@pytest.fixture(params=['start', 'retry'])
def job_admission(request, library, edition_client, monkeypatch):
    from api import database
    from fastapi.testclient import TestClient

    # Each admission test owns its entire real cache directory and lock.
    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', library)
    client = TestClient(edition_client.app, raise_server_exceptions=False)
    route = '/api/export/sidecar_jobs'
    payload = {'paths': ['/unregistered-admission-photo.jpg']}
    if request.param == 'retry':
        response = client.post(route, json=payload)
        assert response.status_code == 202, response.text
        _done(library, response.json()['id'], 'test')
        route += '/' + response.json()['id'] + '/retry'
    try:
        yield library, client, route, payload
    finally:
        client.close()


def test_api_real_held_library_lock_uses_busy_contract(job_admission):
    from facet import LibraryLock
    from api.db_helpers import LIBRARY_BUSY_DETAIL, LIBRARY_BUSY_RETRY_AFTER_SECONDS

    library, client, route, payload = job_admission
    directory = jobs._directory(library)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    with LibraryLock(library, 'scan'):
        response = client.post(route, json=payload)
        assert response.status_code == 503, response.text
        assert response.json() == {'detail': LIBRARY_BUSY_DETAIL}
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['Retry-After'] == str(LIBRARY_BUSY_RETRY_AFTER_SECONDS)
        assert library_job_holder(library)['kind'] == 'scan'
        assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    recovered = client.post(route, json=payload)
    assert recovered.status_code == 202, recovered.text
    assert _done(library, recovered.json()['id'], 'test')['processed'] == 1


@pytest.mark.parametrize('obstruction', ['directory', 'plan', 'receipt'])
def test_api_real_receipt_storage_failure_is_safe_and_recoverable(job_admission, monkeypatch, obstruction):
    from uuid import UUID

    library, client, route, payload = job_admission
    directory = jobs._directory(library)
    existing = {path.name: path.read_bytes() for path in directory.iterdir()}
    job_id = '11111111-1111-4111-8111-111111111111'
    monkeypatch.setattr(jobs, 'uuid4', lambda: UUID(job_id))
    blocker = directory if obstruction == 'directory' else directory / (job_id + ('.plan' if obstruction == 'plan' else '.json'))
    # Real portable publication errors; chmod is ineffective for privileged CI.
    if obstruction == 'directory':
        parked = directory.with_name('parked-receipts')
        directory.rename(parked)
        blocker.write_bytes(b'keep existing obstruction')
    else:
        blocker.mkdir()
        (blocker / 'keep').write_bytes(b'keep existing obstruction')
    runs = []
    original_run = jobs._run
    def run(*args):
        runs.append(args[0])
        return original_run(*args)
    monkeypatch.setattr(jobs, '_run', run)
    response = client.post(route, json=payload)
    assert response.status_code == 503, response.text
    assert response.json() == {'detail': 'Export job storage is unavailable; check server logs and library cache permissions'}
    assert 'Retry-After' not in response.headers
    assert response.headers['Cache-Control'] == 'no-store'
    assert str(Path(library).parent) not in response.text
    assert runs == []
    assert library_job_holder(library) is None
    if obstruction == 'directory':
        assert blocker.read_bytes() == b'keep existing obstruction'
        blocker.unlink()
        parked.rename(directory)
    else:
        assert (blocker / 'keep').read_bytes() == b'keep existing obstruction'
        (blocker / 'keep').unlink()
        blocker.rmdir()
    # Neither a partial plan/receipt nor private temporary files survived.
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == existing
    recovered = client.post(route, json=payload)
    assert recovered.status_code == 202, recovered.text
    result = _done(library, recovered.json()['id'], 'test')
    assert result['processed'] == result['skipped'] == 1
    assert len(runs) == 1



def test_api_real_unusable_library_lock_has_no_retry_hint(job_admission):
    from facet import _library_lock_path

    library, client, route, payload = job_admission
    directory = jobs._directory(library)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    lock_path = Path(_library_lock_path(library))
    lock_path.unlink(missing_ok=True)
    lock_path.mkdir()
    (lock_path / 'keep').write_bytes(b'keep existing obstruction')
    response = client.post(route, json=payload)
    assert response.status_code == 503, response.text
    assert response.json()['detail'] == 'Library lock is unavailable; check server logs and library cache permissions'
    assert 'Retry-After' not in response.headers
    assert response.headers['Cache-Control'] == 'no-store'
    assert str(Path(library).parent) not in response.text
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    assert (lock_path / 'keep').read_bytes() == b'keep existing obstruction'
    (lock_path / 'keep').unlink()
    lock_path.rmdir()
    recovered = client.post(route, json=payload)
    assert recovered.status_code == 202, recovered.text
    assert _done(library, recovered.json()['id'], 'test')['processed'] == 1


@pytest.mark.parametrize('operation', ['recent', 'status', 'cancel'])
def test_job_read_routes_share_safe_storage_error_mapping(library, edition_client, monkeypatch, operation):
    from api import database

    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', library)
    directory = jobs._directory(library)
    directory.rmdir()
    directory.write_bytes(b'keep existing obstruction')
    job_id = '11111111-1111-4111-8111-111111111111'
    route = '/api/export/sidecar_jobs' + ('' if operation == 'recent' else '/' + job_id)
    response = (edition_client.post(route + '/cancel') if operation == 'cancel'
                else edition_client.get(route))
    assert response.status_code == 503, response.text
    assert response.json()['detail'] == 'Export job storage is unavailable; check server logs and library cache permissions'
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'Retry-After' not in response.headers
    assert str(Path(library).parent) not in response.text
    assert directory.read_bytes() == b'keep existing obstruction'
    directory.unlink()
    recovered = (edition_client.post(route + '/cancel') if operation == 'cancel'
                 else edition_client.get(route))
    assert recovered.status_code == (200 if operation == 'recent' else 404)
    assert recovered.headers['Cache-Control'] == 'no-store'


@pytest.mark.skipif(shutil.which('exiftool') is None, reason='requires ExifTool')
def test_background_export_keeps_precondition_details_private_and_recovers(edition_client, tmp_path, seed_photos_prefix, monkeypatch):
    from PIL import Image
    from api import config
    from api.database import DEFAULT_DB_PATH
    from processing.xmp_import import parse_sidecar

    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    images = [tmp_path / name for name in ('broken.jpg', 'good.jpg')]
    for image in images:
        Image.new('RGB', (40, 30), 'blue').save(image)
    originals = [image.read_bytes() for image in images]
    paths = [str(image) for image in images]
    seed_photos_prefix(str(tmp_path), [
        {'path': path, 'filename': image.name, 'star_rating': 4}
        for image, path in zip(images, paths)
    ])
    malformed = b'not valid XMP'
    companion = Path(paths[0] + '.xmp')
    companion.write_bytes(malformed)
    response = edition_client.post('/api/export/sidecar_jobs', json={'paths': paths})
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    owner = jobs._read(jobs._path(DEFAULT_DB_PATH, job_id))['owner']
    result = _done(DEFAULT_DB_PATH, job_id, owner)
    assert result['state'] == 'completed'
    assert (result['processed'], result['written'], result['errors'], result['skipped']) == (2, 1, 1, 0)
    assert result['first_error'] == 'Existing metadata needs repair before exporting'
    assert result['first_error_code'] == 'metadata_repair'
    status = edition_client.get(f'/api/export/sidecar_jobs/{job_id}')
    assert status.status_code == 200
    assert status.json() == result
    assert str(tmp_path) not in status.text
    assert companion.read_bytes() == malformed
    assert parse_sidecar(paths[1] + '.xmp')['star_rating'] == 4
    assert [image.read_bytes() for image in images] == originals
    # Fixing the packet then retrying exports only the refused photo.
    companion.unlink()
    retry = edition_client.post(f'/api/export/sidecar_jobs/{job_id}/retry')
    assert retry.status_code == 202, retry.text
    recovered = _done(DEFAULT_DB_PATH, retry.json()['id'], owner)
    assert recovered['state'] == 'completed'
    assert recovered['total'] == recovered['written'] == 1
    assert recovered['errors'] == recovered['skipped'] == 0
    assert recovered['first_error'] is None
    assert recovered['first_error_code'] is None
    assert parse_sidecar(str(companion))['star_rating'] == 4
    assert [image.read_bytes() for image in images] == originals


def test_old_receipt_errors_stay_private_across_public_endpoints(edition_client):
    from api.database import DEFAULT_DB_PATH

    response = edition_client.post('/api/export/sidecar_jobs', json={'paths': ['/missing-receipt-photo.jpg']})
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    path = jobs._path(DEFAULT_DB_PATH, job_id)
    owner = jobs._read(path)['owner']
    _done(DEFAULT_DB_PATH, job_id, owner)
    # Simulate a receipt written before batch exception strings were sanitized.
    state = jobs._read(path)
    state.update(first_error='Cannot write /private/server/secret.jpg', skipped=0, errors=1)
    jobs._write(path, state)
    before = path.read_bytes()
    status = edition_client.get(f'/api/export/sidecar_jobs/{job_id}')
    recent = edition_client.get('/api/export/sidecar_jobs')
    cancelled = edition_client.post(f'/api/export/sidecar_jobs/{job_id}/cancel')
    for response in (status, recent, cancelled):
        assert response.status_code == 200, response.text
        assert '/private/server/' not in response.text
    returned = [status.json(), next(row for row in recent.json() if row['id'] == job_id), cancelled.json()]
    for row in returned:
        assert row['first_error'] == 'Failed to write metadata; check server logs'
        assert row['first_error_code'] == 'write_failed'
        assert (row['written'], row['errors'], row['skipped']) == (0, 1, 0)
    assert path.read_bytes() == before
