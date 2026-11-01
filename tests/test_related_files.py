"""Real disposable files: inventory is bounded, read-only, scoped and not a stack."""

import hashlib
from pathlib import Path
import sqlite3
import uuid

import pytest

from db import DEFAULT_DB_PATH
from tests.conftest import symlink_or_skip


@pytest.fixture
def files(tmp_path, seed_photos_prefix):
    folder = tmp_path / 'library'
    folder.mkdir()
    photo = folder / 'shot.jpg'
    raw = folder / 'shot.CR2'
    unrelated = folder / 'other.jpg'
    for path in (photo, raw, unrelated):
        path.write_bytes(path.name.encode())
    for suffix in ('.xmp', '.facet.xmp'):
        Path(str(photo) + suffix).write_text('<xmp/>', encoding='utf-8')
    photo.with_suffix('.xmp').write_text('<xmp/>', encoding='utf-8')
    seed_photos_prefix(str(folder) + '/', [
        {'path': str(path), 'filename': path.name} for path in (photo, raw, unrelated)
    ])
    return photo, raw, unrelated


def inventory(client, path, **params):
    result = client.get('/api/photo/related_files', params={'path': str(path), **params})
    assert result.status_code == 200, result.text
    return result.json()


def file_bytes(folder):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir() if path.is_file()}


def test_indexed_pair_and_sidecar_candidates_never_change_files_or_catalog(regular_client, files, monkeypatch):
    photo, raw, unrelated = files
    before_files = file_bytes(photo.parent)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        before_rows = conn.execute('SELECT * FROM photos ORDER BY path').fetchall()
    # Discovery must not enumerate even a small folder.
    monkeypatch.setattr('api.related_files.os.scandir', lambda *args: pytest.fail('directory enumeration'))
    body = inventory(regular_client, photo)
    assert body['inventory_state'] == 'checked'
    entries = {entry['name']: entry for entry in body['files']}
    assert set(entries) == {photo.name, raw.name, 'shot.jpg.xmp', 'shot.xmp', 'shot.jpg.facet.xmp'}
    assert entries[photo.name]['kind'] == 'photo' and entries[photo.name]['indexed'] is True
    assert entries[raw.name]['kind'] == 'raw' and entries[raw.name]['indexed'] is True
    assert entries[raw.name]['raw_download'] is True
    assert body['basename_sidecar_unverified'] is True
    assert unrelated.name not in entries
    assert str(photo.parent) not in str(body)
    # Restore the inspection guard before our own verification enumerates.
    monkeypatch.undo()
    assert file_bytes(photo.parent) == before_files
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT * FROM photos ORDER BY path').fetchall() == before_rows


def test_raw_photo_keeps_own_display_source_and_lists_jpeg_candidate(regular_client, files):
    photo, raw, _ = files
    body = inventory(regular_client, raw)
    primary = body['files'][0]
    assert primary['name'] == raw.name and primary['kind'] == 'photo' and primary['raw_download'] is True
    jpeg = next(entry for entry in body['files'] if entry['name'] == photo.name)
    assert jpeg['kind'] == 'jpeg' and jpeg['indexed'] is True and jpeg['raw_download'] is False


def test_multiple_raw_candidates_are_not_merged_or_arbitrarily_called_one_photo(regular_client, files):
    photo, _, _ = files
    another = photo.with_suffix('.NEF')
    another.write_bytes(b'separate RAW candidate')
    body = inventory(regular_client, photo)
    assert body['multiple_raw_candidates'] is True
    raws = [entry for entry in body['files'] if entry['kind'] == 'raw']
    assert len(raws) == 2 and sum(entry['raw_download'] for entry in raws) == 1


def test_missing_original_is_explicit_and_shared_requests_refuse(regular_client, files):
    photo, _, _ = files
    photo.unlink()
    body = inventory(regular_client, photo)
    assert body['inventory_state'] == 'unavailable'
    assert body['files'] == [{'name': photo.name, 'kind': 'photo', 'indexed': True,
                              'state': 'missing', 'raw_download': False}]
    response = regular_client.get('/api/photo/related_files', params={'path': str(photo), 'token': 'shared'})
    assert response.status_code == 404


def test_raw_symlink_is_reported_as_link_without_resolving_its_target(regular_client, files, tmp_path, monkeypatch):
    photo, raw, _ = files
    raw.unlink()
    target = tmp_path / 'private-foreign-name.bin'
    target.write_bytes(b'private')
    symlink_or_skip(raw, target)
    monkeypatch.setattr('api.related_files.find_companion_raw', lambda *args: pytest.fail('followed companion link'))
    body = inventory(regular_client, photo)
    entry = next(entry for entry in body['files'] if entry['name'] == raw.name)
    assert entry['state'] == 'link' and entry['raw_download'] is False
    assert target.name not in str(body) and str(tmp_path) not in str(body)


def test_invisible_photo_refuses_before_any_disk_inspection(regular_client, files, monkeypatch):
    from api import db_helpers
    photo, _, _ = files
    monkeypatch.setattr(db_helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(db_helpers, 'get_user_directories', lambda user: ['/not-permitted'])
    monkeypatch.setattr('api.related_files.resolve_photo_disk_path', lambda *args: pytest.fail('probed denied photo'))
    response = regular_client.get('/api/photo/related_files', params={'path': str(photo)})
    assert response.status_code == 404


def test_indexed_invisible_candidate_name_is_omitted(regular_client, files, monkeypatch):
    photo, raw, _ = files
    monkeypatch.setattr('api.related_files.get_visibility_clause', lambda user: ('photos.path != ?', [str(raw)]))
    body = inventory(regular_client, photo)
    assert raw.name not in str(body)


def test_mapped_original_must_remain_in_the_callers_roots(regular_client, files, monkeypatch):
    photo, _, _ = files
    monkeypatch.setattr('api.related_files.is_multi_user_enabled', lambda: True)
    monkeypatch.setattr('api.related_files.get_user_directories', lambda user: ['/not-this-users-library'])
    monkeypatch.setattr('api.related_files._state', lambda *args: pytest.fail('inspected outside caller roots'))
    body = inventory(regular_client, photo)
    assert body['inventory_state'] == 'unavailable' and len(body['files']) == 1
    assert body['files'][0]['state'] == 'unavailable'


def test_allowed_path_mapping_keeps_indexed_membership_and_native_names(regular_client, files, seed_photos_prefix, monkeypatch):
    from api import config
    photo, raw, _ = files
    virtual = '/related-virtual/shot.jpg'
    seed_photos_prefix('/related-virtual/', [
        {'path': virtual, 'filename': photo.name},
        {'path': '/related-virtual/shot.CR2', 'filename': raw.name},
    ])
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {'/related-virtual': str(photo.parent)})
    body = inventory(regular_client, virtual)
    entry = next(entry for entry in body['files'] if entry['name'] == raw.name)
    assert entry['indexed'] is True and entry['raw_download'] is True
    assert '/related-virtual/' not in str(body) and str(photo.parent) not in str(body)


def test_other_mapped_catalog_alias_cannot_disclose_private_raw(regular_client, files, seed_photos_prefix, monkeypatch):
    from api import config
    from api import related_files as reader
    photo, raw, _ = files
    seed_photos_prefix('/related-alice/', [{'path': '/related-alice/shot.jpg', 'filename': photo.name}])
    seed_photos_prefix('/related-bob/', [{'path': '/related-bob/shot.CR2', 'filename': raw.name}])
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {
        '/related-alice': str(photo.parent), '/related-bob': str(photo.parent),
    })
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'u1': {'directories': ['/related-alice']}, 'bob': {'directories': ['/related-bob']},
    })
    # Real config, visibility and path-mapping functions, not patched auth.
    assert reader.is_multi_user_enabled() is True
    body = inventory(regular_client, '/related-alice/shot.jpg')
    assert body['inventory_state'] == 'checked' and body['indexed_images_only'] is True
    assert raw.name not in str(body)


def test_manual_stack_does_not_create_a_physical_file_relationship(regular_client, files):
    photo, _, unrelated = files
    before = inventory(regular_client, photo)
    stack_id = str(uuid.uuid4())
    try:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('INSERT INTO photo_stacks(id,owner,cover_path,revision) VALUES (?,?,?,1)',
                         (stack_id, '', str(photo)))
            conn.executemany('INSERT INTO photo_stack_members(stack_id,owner,photo_path,position) VALUES (?,?,?,?)',
                             [(stack_id, '', str(photo), 0), (stack_id, '', str(unrelated), 1)])
        assert inventory(regular_client, photo) == before
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DELETE FROM photo_stack_members WHERE stack_id=?', (stack_id,))
            conn.execute('DELETE FROM photo_stacks WHERE id=?', (stack_id,))
