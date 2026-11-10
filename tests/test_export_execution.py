"""Confirmed jobs: actual disposable file writes, receipts and no retargeting."""

from pathlib import Path
import os
import sqlite3
import threading
from xml.etree import ElementTree as ET

import pytest

from api import config, sidecar_jobs
from db import DEFAULT_DB_PATH
from tests._sidecar_helpers import settle_sidecar_job


# Worker preflight and fsync can be delayed on parallel Windows runners. These
# are event deadlines, not sleeps: fast workers continue as soon as signalled.
WORKER_EVENT_TIMEOUT = 30


@pytest.fixture
def library(tmp_path, seed_photos_prefix, monkeypatch):
    source = tmp_path / 'photos'
    source.mkdir()
    paths = [source / 'alpha.jpg', source / 'beta.jpg']
    for index, path in enumerate(paths):
        path.write_bytes(b'photo\r\n\x1a\x00' + bytes([index]))
    seed_photos_prefix(str(source) + '/', [
        {'path': str(path), 'filename': path.name, 'star_rating': 4, 'caption': 'Exported caption'} for path in paths
    ])
    target = tmp_path / 'delivery'
    target.mkdir()
    monkeypatch.setitem(config.VIEWER_CONFIG, 'export', {'allowed_target_dirs': [str(target)]})
    monkeypatch.setattr('processing.xmp_export.exiftool_available', lambda: False)
    return paths, target


def confirmed_body(client, body):
    result = client.post('/api/export/preview', json=body)
    assert result.status_code == 200, result.text
    preview = result.json()
    return {**body, 'preview_token': preview['preview_token'], 'selected_paths': preview['selected_paths']}, preview


def done(job):
    return settle_sidecar_job(DEFAULT_DB_PATH, job['id'], 'test', timeout=WORKER_EVENT_TIMEOUT)


@pytest.mark.parametrize('racy', [False, True])
@pytest.mark.parametrize('windows', [False, True])
def test_job_naming_cache_only_reuses_stable_change_timestamps(tmp_path, monkeypatch, racy, windows):
    from api import export_execution, export_preview
    from fastapi import HTTPException

    if os.name == 'nt' and not windows:
        pytest.skip('POSIX change-time cache requires POSIX stat semantics')

    source = tmp_path / 'a.jpg'
    source.write_bytes(b'photo')
    now = source.parent.stat().st_ctime_ns + (0 if racy else 10_000_000_000)
    monkeypatch.setattr(export_execution.time, 'time_ns', lambda: now)
    monkeypatch.setattr(export_execution, '_WINDOWS', windows)
    scans = []
    real_scan = export_preview.os.scandir

    def scan(path):
        scans.append(path)
        return real_scan(path)

    monkeypatch.setattr(export_preview.os, 'scandir', scan)
    job = export_execution._Execution('unused', None, None, None, 'unused')
    packet = str(source) + '.xmp'
    job.check_packet_ownership(str(source), [packet])
    job.check_packet_ownership(str(source), [packet])
    assert len(scans) == (2 if racy or windows else 1)
    other_job = export_execution._Execution('unused', None, None, None, 'unused')
    other_job.check_packet_ownership(str(source), [packet])
    assert len(scans) == (3 if racy or windows else 2)
    stamp = tmp_path.stat()
    (tmp_path / 'a.jpg.CR2').write_bytes(b'competing owner')
    os.utime(tmp_path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(HTTPException, match='shared or ambiguous'):
        job.check_packet_ownership(str(source), [packet])


def _stable_job(tmp_path, monkeypatch):
    """A job over a folder that was quiet when the job started; ``clock`` is the job's idea of now."""
    from api import export_execution, export_preview

    source = tmp_path / 'a.jpg'
    source.write_bytes(b'photo')
    clock = [source.parent.stat().st_ctime_ns + 10_000_000_000]
    monkeypatch.setattr(export_execution.time, 'time_ns', lambda: clock[0])
    monkeypatch.setattr(export_execution, '_WINDOWS', False)
    scans = []
    real_scan = export_preview.os.scandir

    def scan(path):
        scans.append(path)
        return real_scan(path)

    monkeypatch.setattr(export_preview.os, 'scandir', scan)
    return export_execution._Execution('unused', None, None, None, 'unused'), source, scans, clock


@pytest.mark.skipif(os.name == 'nt', reason='POSIX change-time cache requires POSIX stat semantics')
def test_job_naming_cache_discards_an_index_built_while_the_folder_changes(tmp_path, monkeypatch):
    from api import export_preview, sidecar_jobs

    job, source, scans, clock = _stable_job(tmp_path, monkeypatch)
    real_check = export_preview._check_packet_claims

    def check_after_a_competitor_appears(disk, packets, claims):
        # The index is complete and clean; the folder changes before the job trusts it.
        (tmp_path / 'a.jpg.CR2').write_bytes(b'competing owner')
        real_check(disk, packets, claims)

    monkeypatch.setattr(export_preview, '_check_packet_claims', check_after_a_competitor_appears)
    with pytest.raises(sidecar_jobs.ExportConditionsChanged):
        job.check_packet_ownership(str(source), [str(source) + '.xmp'])
    assert job.naming_directories == {} and job.naming_key is None


def test_companion_xmp_competitor_between_copy_units_refuses_next_unit(edition_client, library, monkeypatch):
    from api import export_execution

    paths, target = library
    packet = Path(str(paths[0]) + '.xmp')
    packet.write_bytes(b'<xmp>companion</xmp>')
    before = {path: path.read_bytes() for path in [*paths, packet]}
    apply, _ = confirmed_body(edition_client, {'paths': [str(paths[0])], 'mode': 'copy',
                                             'target_dir': str(target), 'include_companions': True})
    deliver = export_execution._deliver

    def introduce_competitor(*args, **kwargs):
        result = deliver(*args, **kwargs)
        Path(str(paths[0]) + '.CR2').write_bytes(b'competing packet owner')
        return result

    monkeypatch.setattr(export_execution, '_deliver', introduce_competitor)
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 202, response.text
    receipt = done(response.json())
    assert receipt['state'] == 'failed' and receipt['first_error_code'] == 'preview_changed', receipt
    assert receipt['written'] == 1
    assert sorted(path.name for path in target.iterdir()) == [paths[0].name]
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize('operation', ['sidecars', 'copy', 'symlink'])
def test_confirmed_job_writes_exact_outputs_and_replay_returns_same_receipt(edition_client, library, operation):
    paths, target = library
    before = {str(path): path.read_bytes() for path in paths}
    body = {'paths': list(map(str, paths)), 'mode': operation}
    if operation != 'sidecars':
        body['target_dir'] = str(target)
    apply, preview = confirmed_body(edition_client, body)
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 202, response.text
    assert response.json()['id'] == preview['receipt_id']
    result = done(response.json())
    assert result['state'] == 'completed' and result['phase'] == 'finished'
    assert result['confirmed'] is True and result['operation'] == operation
    assert result['written'] == result['processed'] == result['total'] == 2
    for path in paths:
        assert path.read_bytes() == before[str(path)]
        if operation == 'sidecars':
            packet = ET.parse(str(path) + '.xmp')
            description = packet.find('.//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description')
            assert description is not None
            assert description.get('{http://ns.adobe.com/xap/1.0/}Rating') == '4'
        else:
            output = target / path.name
            assert output.read_bytes() == before[str(path)]
            assert output.is_symlink() is (operation == 'symlink')
    replay = edition_client.post('/api/export/apply', json=apply)
    assert replay.status_code == 202 and replay.json()['id'] == result['id']
    assert replay.json()['written'] == 2
    if operation != 'sidecars':
        assert sorted(path.name for path in target.iterdir()) == ['alpha.jpg', 'beta.jpg']
    receipt = edition_client.get('/api/export/sidecar_jobs/' + result['id'])
    assert receipt.status_code == 200 and 'photos' not in receipt.text and 'preview_token' not in receipt.text
    retry = edition_client.post('/api/export/sidecar_jobs/' + result['id'] + '/retry')
    assert retry.status_code == 409 and 'fresh' in retry.text


@pytest.mark.parametrize('rotation', [None, 'actor', 'password', 'edition_password', 'secret'])
def test_execution_reuses_credential_derivations_but_stops_on_rotation(
        edition_client, library, monkeypatch, rotation):
    from api import export_execution, export_preview
    paths, target = library
    users = config._FULL_CONFIG.get('users', {})
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        **users, 'test': {**users.get('test', {}), 'password_hash': 'pbkdf2:actor-fixture',
                          'directories': [str(paths[0].parent)]}})
    monkeypatch.setitem(config.VIEWER_CONFIG, 'password', 'viewer fixture')
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'edition fixture')
    body = {'paths': list(map(str, paths)), 'mode': 'copy', 'target_dir': str(target)}
    apply, _ = confirmed_body(edition_client, body)
    derive = export_preview.hashlib.pbkdf2_hmac
    derivations = []

    def counted_derivation(*args, **kwargs):
        derivations.append(1)
        return derive(*args, **kwargs)

    monkeypatch.setattr(export_preview.hashlib, 'pbkdf2_hmac', counted_derivation)
    deliver = export_execution._deliver

    def deliver_and_rotate(item, operation):
        deliver(item, operation)
        if rotation == 'actor':
            # Accounts store only a hash: a reset rewrites password_hash and must stop the job.
            monkeypatch.setitem(config._FULL_CONFIG['users']['test'], 'password_hash', 'pbkdf2:changed-actor')
        elif rotation == 'secret':
            monkeypatch.setattr(config, 'JWT_SECRET', 'changed signing secret')
        elif rotation:
            monkeypatch.setitem(config.VIEWER_CONFIG, rotation, 'changed viewer credential')

    monkeypatch.setattr(export_execution, '_deliver', deliver_and_rotate)
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 202, response.text
    result = done(response.json())
    assert (target / paths[0].name).read_bytes() == paths[0].read_bytes()
    if rotation:
        assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed'
        assert result['written'] == 1
        assert not (target / paths[1].name).exists()
    else:
        assert result['state'] == 'completed' and result['written'] == 2
        assert (target / paths[1].name).read_bytes() == paths[1].read_bytes()
        # Two preflight policy reads plus one derivation per distinct credential
        # during execution, independent of the number of files copied.
        assert len(derivations) == 9


def test_change_before_admission_refuses_entire_scope_before_any_target_write(edition_client, library):
    paths, target = library
    apply, _ = confirmed_body(edition_client, {'paths': list(map(str, paths))})
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET star_rating=1 WHERE path=?', (str(paths[1]),))
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 202
    result = done(response.json())
    assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed'
    assert result['written'] == result['processed'] == 0
    assert not list(paths[0].parent.glob('*.xmp')) and not list(target.iterdir())
    retry = edition_client.post('/api/export/sidecar_jobs/' + result['id'] + '/preview')
    assert retry.status_code == 200, retry.text
    captured = retry.json()
    assert captured['selected_paths'] == list(map(str, paths)) and captured['ready'] == 2
    assert [item['metadata']['xmp_rating'] for item in captured['items']] == [4, 1]
    assert not list(paths[0].parent.glob('*.xmp'))
    applied = edition_client.post('/api/export/apply', json={**captured['request'],
        'preview_token': captured['preview_token'], 'selected_paths': captured['selected_paths']})
    assert applied.status_code == 202, applied.text
    assert done(applied.json())['written'] == 2


def test_new_competing_packet_owner_stops_later_files_even_with_unchanged_directory_mtime(
        edition_client, library, monkeypatch):
    from api import export_execution

    paths, _ = library
    apply, _ = confirmed_body(edition_client, {'paths': list(map(str, paths))})
    before = {path: path.read_bytes() for path in paths}
    real_write = export_execution.write_confirmed_metadata

    def write_then_introduce_competitor(*args, **kwargs):
        result = real_write(*args, **kwargs)
        folder = paths[0].parent
        stamp = folder.stat()
        Path(str(paths[1]) + '.CR2').write_bytes(b'new owner of beta.jpg.xmp')
        os.utime(folder, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert folder.stat().st_mtime_ns == stamp.st_mtime_ns
        return result

    monkeypatch.setattr(export_execution, 'write_confirmed_metadata', write_then_introduce_competitor)
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 202, response.text
    result = done(response.json())
    assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed'
    assert result['processed'] == result['written'] == 1
    assert Path(str(paths[0]) + '.xmp').is_file()
    assert not Path(str(paths[1]) + '.xmp').exists()
    assert {path: path.read_bytes() for path in paths} == before


def test_later_metadata_change_stops_new_files_and_retains_written_prefix(edition_client, library, monkeypatch):
    from api import export_execution
    paths, _ = library
    apply, _ = confirmed_body(edition_client, {'paths': list(map(str, paths))})
    entered, release = threading.Event(), threading.Event()
    real_write = export_execution.write_confirmed_metadata

    def write_then_pause(*args, **kwargs):
        result = real_write(*args, **kwargs)
        entered.set()
        assert release.wait(WORKER_EVENT_TIMEOUT)
        return result

    monkeypatch.setattr(export_execution, 'write_confirmed_metadata', write_then_pause)
    response = edition_client.post('/api/export/apply', json=apply)
    try:
        assert response.status_code == 202, response.text
        assert entered.wait(WORKER_EVENT_TIMEOUT), sidecar_jobs.status(DEFAULT_DB_PATH, response.json()["id"], "test")
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('UPDATE photos SET star_rating=1 WHERE path=?', (str(paths[1]),))
    finally:
        release.set()
    result = done(response.json())
    assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed'
    assert result['processed'] == result['written'] == 1
    assert Path(str(paths[0]) + '.xmp').is_file() and not Path(str(paths[1]) + '.xmp').exists()
    completed_packet = Path(str(paths[0]) + '.xmp').read_bytes()
    retry = edition_client.post('/api/export/sidecar_jobs/' + result['id'] + '/preview')
    assert retry.status_code == 200, retry.text
    captured = retry.json()
    assert captured['selected_paths'] == [str(paths[1])] and captured['ready'] == 1
    assert captured['items'][0]['metadata']['xmp_rating'] == 1
    applied = edition_client.post('/api/export/apply', json={**captured['request'],
        'preview_token': captured['preview_token'], 'selected_paths': captured['selected_paths']})
    assert applied.status_code == 202, applied.text
    final = done(applied.json())
    assert final['state'] == 'completed' and final['written'] == 1
    assert Path(str(paths[0]) + '.xmp').read_bytes() == completed_packet


def test_copy_accepts_windows_descriptor_ctime_difference_but_checks_path(tmp_path, monkeypatch):
    from api import export_execution
    from api.export_preview import _identity
    source, target = tmp_path / 'source.jpg', tmp_path / 'copy.jpg'
    source.write_bytes(b'original')
    item = {'source': str(source), 'target': str(target), 'source_identity': _identity(str(source))}
    real_identity = export_execution._stat_identity
    monkeypatch.setattr(export_execution, '_WINDOWS', True, raising=False)
    monkeypatch.setattr(export_execution, '_stat_identity', lambda stat: [*real_identity(stat)[:4], real_identity(stat)[4] + 1])
    export_execution._deliver(item, 'copy')
    assert target.read_bytes() == b'original'


def test_copy_refuses_changed_path_identity_before_creating_target(tmp_path, monkeypatch):
    from api import export_execution
    from api.export_preview import _identity
    source, target = tmp_path / 'source.jpg', tmp_path / 'copy.jpg'
    source.write_bytes(b'original')
    item = {'source': str(source), 'target': str(target), 'source_identity': _identity(str(source))}
    monkeypatch.setattr(export_execution, '_WINDOWS', True)
    monkeypatch.setattr(export_execution, '_identity', lambda path: [*item['source_identity'][:4], item['source_identity'][4] + 1])
    with pytest.raises(sidecar_jobs.ExportConditionsChanged):
        export_execution._deliver(item, 'copy')
    assert not target.exists()


def test_cancellation_keeps_completed_file_and_never_starts_next(edition_client, library, monkeypatch):
    from api import export_execution
    paths, target = library
    apply, _ = confirmed_body(edition_client, {'paths': list(map(str, paths)), 'mode': 'copy', 'target_dir': str(target)})
    entered, release = threading.Event(), threading.Event()
    real_deliver = export_execution._deliver

    def deliver_then_pause(*args):
        real_deliver(*args)
        entered.set()
        assert release.wait(WORKER_EVENT_TIMEOUT)

    monkeypatch.setattr(export_execution, '_deliver', deliver_then_pause)
    response = edition_client.post('/api/export/apply', json=apply)
    try:
        assert response.status_code == 202, response.text
        assert entered.wait(WORKER_EVENT_TIMEOUT), sidecar_jobs.status(DEFAULT_DB_PATH, response.json()["id"], "test")
        sidecar_jobs.cancel(DEFAULT_DB_PATH, response.json()['id'], 'test')
    finally:
        release.set()
    result = done(response.json())
    assert result['state'] == 'cancelled' and result['written'] == 1
    assert (target / paths[0].name).read_bytes() == paths[0].read_bytes()
    assert not (target / paths[1].name).exists()


def test_tampered_captured_membership_does_not_start_a_job(edition_client, library):
    paths, target = library
    apply, preview = confirmed_body(edition_client, {'paths': list(map(str, paths)), 'mode': 'copy', 'target_dir': str(target)})
    apply['selected_paths'] = [str(paths[0])]
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 409
    assert edition_client.get('/api/export/sidecar_jobs/' + preview['receipt_id']).status_code == 404
    assert not list(target.iterdir())


def test_new_packet_owner_after_preflight_stops_the_next_sidecar(edition_client, library, monkeypatch):
    from api import export_execution
    paths, _ = library
    apply, _ = confirmed_body(edition_client, {'paths': list(map(str, paths)), 'overwrite': True})
    entered, release = threading.Event(), threading.Event()
    real_write = export_execution.write_confirmed_metadata

    def write_then_pause(*args, **kwargs):
        real_write(*args, **kwargs)
        entered.set()
        assert release.wait(WORKER_EVENT_TIMEOUT)

    monkeypatch.setattr(export_execution, 'write_confirmed_metadata', write_then_pause)
    response = edition_client.post('/api/export/apply', json=apply)
    try:
        assert entered.wait(WORKER_EVENT_TIMEOUT), sidecar_jobs.status(DEFAULT_DB_PATH, response.json()["id"], "test")
        Path(str(paths[1]) + '.png').write_bytes(b'new photo claiming the packet by basename')
    finally:
        release.set()
    result = done(response.json())
    assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed'
    assert result['written'] == result['processed'] == 1
    assert not Path(str(paths[1]) + '.xmp').exists()


@pytest.mark.parametrize('mode', ['copy', 'symlink'])
@pytest.mark.parametrize('missing_companion', [False, True])
def test_retry_preview_keeps_unfinished_companions_without_redelivering_completed_photo(edition_client, library, monkeypatch, mode, missing_companion):
    from api import export_execution
    paths, target = library
    packet = Path(str(paths[0]) + '.xmp')
    packet.write_bytes(b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>')
    apply, _ = confirmed_body(edition_client, {'paths': list(map(str, paths)), 'mode': mode,
                                             'target_dir': str(target), 'include_companions': True})
    entered, release = threading.Event(), threading.Event()
    real_deliver = export_execution._deliver

    def pause(*args):
        real_deliver(*args)
        entered.set()
        assert release.wait(WORKER_EVENT_TIMEOUT)

    monkeypatch.setattr(export_execution, '_deliver', pause)
    response = edition_client.post('/api/export/apply', json=apply)
    try:
        assert response.status_code == 202, response.text
        assert entered.wait(WORKER_EVENT_TIMEOUT), sidecar_jobs.status(DEFAULT_DB_PATH, response.json()["id"], "test")
        sidecar_jobs.cancel(DEFAULT_DB_PATH, response.json()['id'], 'test')
    finally:
        release.set()
    first = done(response.json())
    assert first['state'] == 'cancelled' and first['processed'] == first['written'] == 1
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    packet_bytes = packet.read_bytes()
    if missing_companion:
        packet.unlink()
    retry = edition_client.post('/api/export/sidecar_jobs/' + first['id'] + '/preview')
    assert retry.status_code == 200, retry.text
    captured = retry.json()
    assert captured['ready'] == (1 if missing_companion else 2)
    assert captured['missing'] == (1 if missing_companion else 0)
    assert {item['source_name'] for item in captured['items']} == {'alpha.jpg.xmp', 'beta.jpg'}
    assert {item['target_name'] for item in captured['items']} == {'alpha.jpg.xmp', 'beta.jpg'}
    assert {p.name: p.read_bytes() for p in target.iterdir()} == before
    tampered = {**captured['request'], 'paths': [str(paths[1])]}
    refused = edition_client.post('/api/export/preview', json=tampered)
    assert refused.status_code == 409
    applied = edition_client.post('/api/export/apply', json={**captured['request'],
        'preview_token': captured['preview_token'], 'selected_paths': captured['selected_paths']})
    assert applied.status_code == 202, applied.text
    result = done(applied.json())
    assert result['state'] == 'completed' and result['processed'] == 2
    assert result['written'] == (1 if missing_companion else 2)
    if missing_companion:
        assert result['skipped'] == 1
        packet.write_bytes(packet_bytes)
        third = edition_client.post('/api/export/sidecar_jobs/' + result['id'] + '/preview')
        assert third.status_code == 200, third.text
        captured = third.json()
        assert captured['ready'] == 1 and captured['missing'] == 0
        assert [item['source_name'] for item in captured['items']] == ['alpha.jpg.xmp']
        assert all('source' not in item and 'target' not in item for item in captured['items'])
        completed = edition_client.post('/api/export/apply', json={**captured['request'],
            'preview_token': captured['preview_token'], 'selected_paths': captured['selected_paths']})
        assert completed.status_code == 202, completed.text
        result = done(completed.json())
        assert result['state'] == 'completed' and result['written'] == result['processed'] == 1
    assert sorted(p.name for p in target.iterdir()) == ['alpha.jpg', 'alpha.jpg.xmp', 'beta.jpg']
    assert (target / 'alpha.jpg').read_bytes() == before['alpha.jpg']
    assert (target / 'alpha.jpg.xmp').read_bytes() == packet.read_bytes()


def test_retry_preview_refuses_an_occupied_unfinished_destination(edition_client, library, monkeypatch):
    from api import export_execution
    paths, target = library
    apply, _ = confirmed_body(edition_client, {'paths': list(map(str, paths)), 'mode': 'copy', 'target_dir': str(target)})
    entered, release = threading.Event(), threading.Event()
    real_deliver = export_execution._deliver

    def pause(*args):
        real_deliver(*args)
        entered.set()
        assert release.wait(WORKER_EVENT_TIMEOUT)

    monkeypatch.setattr(export_execution, '_deliver', pause)
    response = edition_client.post('/api/export/apply', json=apply)
    try:
        assert entered.wait(WORKER_EVENT_TIMEOUT), sidecar_jobs.status(DEFAULT_DB_PATH, response.json()["id"], "test")
        sidecar_jobs.cancel(DEFAULT_DB_PATH, response.json()['id'], 'test')
    finally:
        release.set()
    first = done(response.json())
    occupied = target / paths[1].name
    occupied.write_bytes(b'output requiring manual inspection')
    retry = edition_client.post('/api/export/sidecar_jobs/' + first['id'] + '/preview')
    assert retry.status_code == 409, retry.text
    assert occupied.read_bytes() == b'output requiring manual inspection'
    assert sorted(p.name for p in target.iterdir()) == ['alpha.jpg', 'beta.jpg']


@pytest.mark.parametrize('scope_kind', ['whole_view', 'smart_album'])
def test_preview_and_apply_keep_folded_matching_members_and_explicit_exclusions(edition_client, library, scope_kind):
    import json
    paths, target = library
    stack = edition_client.post('/api/stacks', json={'paths': list(map(str, paths)), 'cover_path': str(paths[0])})
    assert stack.status_code == 201, stack.text
    filters = {'path_prefix': str(paths[0].parent) + '/'}
    if scope_kind == 'smart_album':
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            album = conn.execute('INSERT INTO albums(name,user_id,is_smart,smart_filter_json) VALUES(?,?,1,?)',
                                 ('delivery fixture', 'test', json.dumps(filters))).lastrowid
            conn.executemany('INSERT INTO album_photos(album_id,photo_path) VALUES(?,?)', [(album, str(path)) for path in paths])
        filters['album_id'] = str(album)
        scope = {'album_id': album}
    else:
        scope = {'filters': filters}
    page = edition_client.get('/api/photos', params={**filters, 'per_page': 1})
    assert page.status_code == 200, page.text
    assert len(page.json()['photos']) == 1 and page.json()['photo_total'] == 2
    assert page.json()['photos'][0]['path'] == str(paths[0])
    body = {**scope, 'exclude': [str(paths[0])], 'mode': 'copy', 'target_dir': str(target)}
    apply, captured = confirmed_body(edition_client, body)
    assert captured['selected_paths'] == [str(paths[1])]
    assert not list(target.iterdir())
    result = edition_client.post('/api/export/apply', json=apply)
    assert result.status_code == 202, result.text
    assert done(result.json())['written'] == 1
    assert [p.name for p in target.iterdir()] == [paths[1].name]
    assert (target / paths[1].name).read_bytes() == paths[1].read_bytes()


@pytest.fixture
def logical_pair(library, seed_photos_prefix):
    from db import logical_assets, logical_review
    path = library[0][0]
    raw = path.with_suffix('.CR2')
    raw.write_bytes(b'private RAW fixture')
    seed_photos_prefix(str(path.parent) + '/', [{'path': str(raw), 'filename': raw.name, 'star_rating': 1}])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN IMMEDIATE')
        key = logical_assets.create(conn, [str(path), str(raw)], str(raw), visibility_sql='1=1')
        logical_review.seed(conn, key, str(path), 1, visibility_sql='1=1')
    return key, path, raw


@pytest.mark.parametrize('personal', [False, True])
def test_logical_review_export_uses_shared_rating_on_explicit_file_target(edition_client, library, logical_pair, monkeypatch, personal):
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key, path, raw = logical_pair
    if personal:
        monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': [str(path.parent)]}})
    response = edition_client.post('/api/photo/set_rating', json={'photo_path': str(raw), 'rating': 5})
    assert response.status_code == 200, response.text
    apply, preview = confirmed_body(edition_client, {'paths': [str(path)]})
    metadata = preview['items'][0]['metadata']
    assert metadata['star_rating'] == metadata['xmp_rating'] == 5
    assert metadata['caption'] == 'Exported caption'
    assert metadata['review_authority'] == 'logical'
    assert metadata['review_scope'] == ('personal' if personal else 'catalog')
    assert next(item for item in metadata['provenance']['review'] if item['field'] == 'star_rating')['source'] == 'local'
    assert 'logical_review_guard' not in str(preview) and key not in str(preview)
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 202, response.text
    result = done(response.json())
    assert result['state'] == 'completed', result
    description = ET.parse(str(path) + '.xmp').find('.//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description')
    assert description.get('{http://ns.adobe.com/xap/1.0/}Rating') == '5'
    assert not Path(str(raw) + '.xmp').exists()
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (str(path),)).fetchone()[0] == 4
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (str(raw),)).fetchone()[0] == 1


def test_logical_export_inherits_file_provenance_and_marks_unknown_fields(edition_client, library, logical_pair):
    from db.metadata_edits import record_sidecar_receipt

    _, path, _ = logical_pair
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET star_rating=3 WHERE path=?', (str(path),))
        record_sidecar_receipt(conn, str(path), None, ['star_rating'], 'private.xmp', '2026-01-01')
    _, preview = confirmed_body(edition_client, {'paths': [str(path)]})
    provenance = {item['field']: item for item in preview['items'][0]['metadata']['provenance']['review']}
    assert provenance['star_rating']['source'] == 'xmp'
    assert provenance['star_rating']['source_at'] == '2026-01-01'
    assert provenance['is_favorite']['source'] == 'unrecorded'
    assert 'private.xmp' not in str(preview)


@pytest.mark.parametrize('change', ['review_aba', 'primary', 'dissolve'])
def test_logical_export_guard_refuses_changed_authority_before_any_write(
        edition_client, library, logical_pair, monkeypatch, change):
    from db import logical_assets
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key, path, raw = logical_pair
    assert edition_client.post('/api/photo/set_rating', json={'photo_path': str(raw), 'rating': 5}).status_code == 200
    apply, _ = confirmed_body(edition_client, {'paths': [str(path)]})
    if change == 'review_aba':
        for value in (3, 5):
            assert edition_client.post('/api/photo/set_rating', json={'photo_path': str(raw), 'rating': value}).status_code == 200
    else:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('BEGIN IMMEDIATE')
            if change == 'primary':
                logical_assets.set_primary(conn, key, str(path), 1, visibility_sql='1=1')
            else:
                logical_assets.dissolve(conn, key, 1, visibility_sql='1=1')
    response = edition_client.post('/api/export/apply', json=apply)
    assert response.status_code == 202, response.text
    result = done(response.json())
    assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed', result
    assert result['written'] == result['processed'] == 0
    assert not Path(str(path) + '.xmp').exists()
    assert not Path(str(raw) + '.xmp').exists()


def test_logical_export_refuses_hidden_member_without_disclosing_it(edition_client, library, logical_pair, monkeypatch):
    from api import logical_reviews
    _, path, raw = logical_pair
    monkeypatch.setattr(logical_reviews, 'get_visibility_clause', lambda owner: ('photos.path != ?', [str(raw)]))
    response = edition_client.post('/api/export/preview', json={'paths': [str(path)]})
    assert response.status_code == 404, response.text
    assert str(raw) not in response.text
    assert not Path(str(path) + '.xmp').exists()


def test_logical_primary_change_between_files_stops_remaining_sidecar(edition_client, library, logical_pair, seed_photos_prefix, monkeypatch):
    from api import export_execution
    from db import logical_assets
    key, path, _ = logical_pair
    first = path.with_name('0-first.jpg')
    first.write_bytes(b'first independent file')
    seed_photos_prefix(str(path.parent) + '/', [{'path': str(first), 'filename': first.name, 'star_rating': 4}])
    apply, preview = confirmed_body(edition_client, {'paths': [str(first), str(path)]})
    assert preview['selected_paths'] == [str(first), str(path)]
    entered, release = threading.Event(), threading.Event()
    real_write = export_execution.write_confirmed_metadata

    def write_then_pause(*args, **kwargs):
        result = real_write(*args, **kwargs)
        entered.set()
        assert release.wait(WORKER_EVENT_TIMEOUT)
        return result

    monkeypatch.setattr(export_execution, 'write_confirmed_metadata', write_then_pause)
    response = edition_client.post('/api/export/apply', json=apply)
    try:
        assert response.status_code == 202, response.text
        assert entered.wait(WORKER_EVENT_TIMEOUT), sidecar_jobs.status(DEFAULT_DB_PATH, response.json()["id"], "test")
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('BEGIN IMMEDIATE')
            logical_assets.set_primary(conn, key, str(path), 1, visibility_sql='1=1')
    finally:
        release.set()
    result = done(response.json())
    assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed', result
    assert result['processed'] == result['written'] == 1
    assert Path(str(first) + '.xmp').is_file()
    assert not Path(str(path) + '.xmp').exists()


def test_filter_delivery_matches_logical_gallery_and_uses_chosen_primary(edition_client, library, logical_pair):
    _, path, raw = logical_pair
    filters = {'path_prefix': str(path.parent) + '/'}
    result = edition_client.post('/api/export/preview', json={'filters': filters, 'mode': 'copy', 'target_dir': str(library[1])})
    assert result.status_code == 200, result.text
    preview = result.json()
    assert set(preview['selected_paths']) == {str(raw), str(library[0][1])}
    assert preview['ready'] == 2
    assert not list(library[1].iterdir())
    response = edition_client.post('/api/export/apply', json={**preview['request'], 'preview_token': preview['preview_token'], 'selected_paths': preview['selected_paths']})
    assert response.status_code == 202, response.text
    result = done(response.json())
    assert result['state'] == 'completed' and result['written'] == 2, result
    assert {item.name for item in library[1].iterdir()} == {raw.name, library[0][1].name}
    assert (library[1] / raw.name).read_bytes() == raw.read_bytes()


def test_logical_collection_export_excludes_entire_group_by_either_alias(edition_client, library, logical_pair):
    _, path, raw = logical_pair
    for alias in (path, raw):
        result = edition_client.post('/api/export/preview', json={'filters': {'path_prefix': str(path.parent) + '/'},
            'exclude': [str(alias)], 'mode': 'copy', 'target_dir': str(library[1])})
        assert result.status_code == 200, result.text
        assert result.json()['selected_paths'] == [str(library[0][1])]


@pytest.mark.parametrize('smart', [False, True])
def test_album_delivery_uses_logical_membership_and_explicit_primary(edition_client, library, logical_pair, album_factory, smart):
    _, path, raw = logical_pair
    album = album_factory(str(path.parent) + os.sep, 'logical-album-export', 'Chosen')(
        smart_filter={'path_prefix': str(path.parent) + '/', 'min_star_rating': '4'} if smart else None,
        member_names=('alpha.jpg',))
    result = edition_client.post('/api/export/preview', json={'album_id': album, 'mode': 'copy', 'target_dir': str(library[1])})
    assert result.status_code == 200, result.text
    expected = {str(raw), str(library[0][1])} if smart else {str(raw)}
    assert set(result.json()['selected_paths']) == expected


def test_missing_primary_refuses_collection_export_but_keeps_explicit_file_export(edition_client, library, logical_pair):
    key, path, raw = logical_pair
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM photos WHERE path=?', (str(raw),))
    result = edition_client.post('/api/export/preview', json={'filters': {'path_prefix': str(path.parent) + '/'},
        'mode': 'copy', 'target_dir': str(library[1])})
    assert result.status_code == 409, result.text
    explicit = edition_client.post('/api/export/preview', json={'paths': [str(path)], 'mode': 'copy', 'target_dir': str(library[1])})
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()['selected_paths'] == [str(path)]
    assert not list(library[1].iterdir())


def test_collection_primary_change_between_copy_files_stops_the_old_representation(
        edition_client, library, logical_pair, seed_photos_prefix, monkeypatch):
    from api import export_execution
    from db import logical_assets
    key, path, raw = logical_pair
    first = path.with_name('0-first.jpg')
    first.write_bytes(b'first independent file')
    seed_photos_prefix(str(path.parent) + '/', [{'path': str(first), 'filename': first.name, 'star_rating': 4}])
    apply, preview = confirmed_body(edition_client, {'filters': {'path_prefix': str(path.parent) + '/'},
        'mode': 'copy', 'target_dir': str(library[1])})
    assert preview['selected_paths'][0] == str(first)
    entered, release = threading.Event(), threading.Event()
    real_deliver = export_execution._deliver

    def deliver_then_pause(*args, **kwargs):
        result = real_deliver(*args, **kwargs)
        entered.set()
        assert release.wait(WORKER_EVENT_TIMEOUT)
        return result

    monkeypatch.setattr(export_execution, '_deliver', deliver_then_pause)
    response = edition_client.post('/api/export/apply', json=apply)
    try:
        assert response.status_code == 202, response.text
        assert entered.wait(WORKER_EVENT_TIMEOUT), sidecar_jobs.status(DEFAULT_DB_PATH, response.json()["id"], "test")
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('BEGIN IMMEDIATE')
            logical_assets.set_primary(conn, key, str(path), 1, visibility_sql='1=1')
    finally:
        release.set()
    result = done(response.json())
    assert result['state'] == 'failed' and result['first_error_code'] == 'preview_changed', result
    assert result['written'] == result['processed'] == 1
    assert {item.name for item in library[1].iterdir()} == {first.name}
    assert not (library[1] / raw.name).exists()


def test_smart_album_export_does_not_fall_back_to_stale_manual_members(edition_client, library, logical_pair, album_factory):
    _, path, _ = logical_pair
    album = album_factory(str(path.parent) + '/', 'stale-smart-export', 'Chosen')(
        smart_filter={'path_prefix': str(path.parent) + '/', 'category': 'no-match-fixture'}, member_names=('alpha.jpg',))
    result = edition_client.post('/api/export/preview', json={'album_id': album, 'mode': 'copy', 'target_dir': str(library[1])})
    assert result.status_code == 422, result.text
    assert not list(library[1].iterdir())


@pytest.mark.parametrize('owner', ['', 'someone-else'])
@pytest.mark.parametrize('smart', [False, True])
def test_album_export_uses_normal_album_ownership_on_protected_install(
        edition_client, library, album_factory, monkeypatch, owner, smart):
    path = library[0][0]
    album = album_factory(str(path.parent) + '/', 'private-export-album', 'Private')(
        smart_filter={'path_prefix': str(path.parent) + '/'} if smart else None, member_names=(path.name,))
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE albums SET user_id=? WHERE id=?', (owner, album))
    monkeypatch.setitem(config.VIEWER_CONFIG, 'password', 'protected-fixture')
    response = edition_client.post('/api/export/preview', json={'album_id': album, 'mode': 'copy', 'target_dir': str(library[1])})
    assert response.status_code == 403, response.text
    assert str(path) not in response.text
    assert not list(library[1].iterdir())
