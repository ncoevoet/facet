"""Companion expansion cannot grant writes to another account's indexed files."""
from pathlib import Path
import sqlite3

import pytest

from api import config
from db import DEFAULT_DB_PATH
from tests.conftest import symlink_or_skip


@pytest.fixture
def library(tmp_path, seed_photos_prefix, monkeypatch):
    def make(*, hidden=False, personal=False, indexed=True):
        folder = tmp_path / 'source'
        folder.mkdir()
        jpg, raw = folder / 'shot.jpg', folder / 'shot.CR2'
        jpg.write_bytes(b'JPEG fixture')
        raw.write_bytes(b'RAW fixture')
        target = tmp_path / 'target'
        target.mkdir()
        if personal:
            paths = ['/companion-alice/shot.jpg', '/companion-bob/shot.CR2']
            monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {
                '/companion-alice': str(folder), '/companion-bob': str(folder)})
            monkeypatch.setitem(config._FULL_CONFIG, 'users', {
                'test': {'directories': ['/companion-alice'] if hidden else ['/companion-alice', '/companion-bob']},
                'bob': {'directories': ['/companion-bob']}})
            for path in paths[:2 if indexed else 1]:
                seed_photos_prefix(str(Path(path).parent) + '/', [{'path': path, 'filename': Path(path).name}])
        else:
            paths = [str(jpg), str(raw)]
            monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
            seed_photos_prefix(str(folder) + '/', [{'path': path, 'filename': Path(path).name} for path in paths[:2 if indexed else 1]])
        monkeypatch.setitem(config.VIEWER_CONFIG, 'cull', {'allow_trash': True})
        monkeypatch.setitem(config.VIEWER_CONFIG, 'export', {'allowed_target_dirs': [str(target)]})
        return jpg, raw, paths, target
    return make


def request(client, paths, target, action, dry_run, *, assert_unchanged=False):
    rejected = int(action in ('move_rejects', 'trash_rejects'))
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET is_rejected=? WHERE path=?', (rejected, paths[0]))
        conn.execute('INSERT OR REPLACE INTO user_preferences(user_id,photo_path,is_rejected) VALUES (?,?,?)', ('test', paths[0], rejected))
    def rows():
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            return (conn.execute('SELECT * FROM photos WHERE path IN (?,?) ORDER BY path', paths).fetchall(),
                    conn.execute('SELECT * FROM user_preferences WHERE photo_path IN (?,?) ORDER BY user_id, photo_path', paths).fetchall())
    before = rows() if assert_unchanged else None
    body = {'paths': [paths[0]], 'include_companions': True, 'dry_run': dry_run}
    if action == 'delete':
        response = client.post('/api/photo/delete', json=body)
    else:
        response = client.post('/api/cull/apply', json={**body, 'action': action, 'target_dir': str(target)})
    if assert_unchanged:
        assert rows() == before
    return response


@pytest.mark.parametrize('action', ['delete', 'copy_keeps', 'move_rejects', 'trash_rejects'])
@pytest.mark.parametrize('dry_run', [True, False])
def test_hidden_mapped_raw_refuses_whole_request_without_file_or_row_changes(edition_client, library, monkeypatch, action, dry_run):
    import send2trash
    monkeypatch.setattr(send2trash, 'send2trash', lambda *_: pytest.fail('hidden companion must refuse before trash'))
    jpg, raw, paths, target = library(hidden=True, personal=True)
    before = {path: path.read_bytes() for path in (jpg, raw)}
    response = request(edition_client, paths, target, action, dry_run, assert_unchanged=True)
    assert response.status_code == 403, response.text
    assert {path: path.read_bytes() for path in (jpg, raw)} == before
    assert not list(target.iterdir())
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE path IN (?,?)', paths).fetchone()[0] == 2


@pytest.mark.parametrize('personal,indexed', [(True, True), (False, True), (False, False)])
def test_authorized_companion_copy_preserves_both_originals(edition_client, library, personal, indexed):
    jpg, raw, paths, target = library(personal=personal, indexed=indexed)
    response = request(edition_client, paths, target, 'copy_keeps', False)
    assert response.status_code == 200, response.text
    assert response.json()['copied'] == 2
    for source in (jpg, raw):
        assert (target / source.name).read_bytes() == source.read_bytes()


def test_authorized_trash_removes_both_files_and_indexed_rows(edition_client, library, monkeypatch):
    import send2trash
    jpg, raw, paths, target = library()
    def trash(source):
        source = Path(source)
        assert source.parent == jpg.parent
        source.rename(target / source.name)
    monkeypatch.setattr(send2trash, 'send2trash', trash)
    response = request(edition_client, paths, target, 'delete', False)
    assert response.status_code == 200, response.text
    assert set(response.json()['deleted']) == set(paths)
    assert not jpg.exists() and not raw.exists()
    assert (target / raw.name).read_bytes() == b'RAW fixture'
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE path IN (?,?)', paths).fetchone()[0] == 0


@pytest.mark.parametrize('unsafe', ['link', 'directory', 'ambiguous'])
def test_unsafe_inventory_refuses_before_trashing_the_primary(edition_client, library, monkeypatch, unsafe):
    import send2trash
    jpg, raw, paths, target = library()
    if unsafe == 'ambiguous':
        raw.with_suffix('.NEF').write_bytes(b'another RAW')
    else:
        raw.unlink()
        if unsafe == 'directory':
            raw.mkdir()
        else:
            other = target / 'private.CR2'
            other.write_bytes(b'private')
            symlink_or_skip(raw, other)
    monkeypatch.setattr(send2trash, 'send2trash', lambda *_: pytest.fail('write before complete companion preflight'))
    response = request(edition_client, paths, target, 'delete', False, assert_unchanged=True)
    assert response.status_code == 409, response.text
    assert jpg.read_bytes() == b'JPEG fixture'
    if unsafe == 'ambiguous':
        assert raw.read_bytes() == b'RAW fixture'
        assert raw.with_suffix('.NEF').read_bytes() == b'another RAW'
    elif unsafe == 'directory':
        assert raw.is_dir() and not list(raw.iterdir())
    else:
        assert raw.is_symlink() and raw.read_bytes() == b'private'


@pytest.mark.parametrize('action', ['delete', 'copy_keeps'])
def test_later_hidden_bundle_refuses_before_processing_earlier_visible_photo(
        edition_client, library, seed_photos_prefix, monkeypatch, action):
    import send2trash
    jpg, raw, paths, target = library(hidden=True, personal=True)
    first = jpg.with_name('first.jpg')
    first.write_bytes(b'first visible photo')
    first_path = '/companion-alice/first.jpg'
    seed_photos_prefix('/companion-alice/', [{'path': first_path, 'filename': first.name}])
    monkeypatch.setattr(send2trash, 'send2trash', lambda *_: pytest.fail('all bundles must pass before first write'))
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        before_rows = conn.execute('SELECT * FROM photos ORDER BY path').fetchall()
    body = {'paths': [first_path, paths[0]], 'include_companions': True, 'dry_run': False}
    if action == 'delete':
        response = edition_client.post('/api/photo/delete', json=body)
    else:
        response = edition_client.post('/api/cull/apply', json={**body, 'action': action, 'target_dir': str(target)})
    assert response.status_code == 403, response.text
    assert first.read_bytes() == b'first visible photo'
    assert jpg.read_bytes() == b'JPEG fixture'
    assert raw.read_bytes() == b'RAW fixture'
    assert not list(target.iterdir())
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT * FROM photos ORDER BY path').fetchall() == before_rows
