"""Viewer exports publish complete snapshots and preserve private destination state."""

import os
import sqlite3
import struct
from contextlib import closing
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from db import maintenance
from db.schema import init_database


def _library(path, caption='source'):
    init_database(str(path), build_photo_indexes=False)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO photos(path,filename,caption) VALUES('/photo.jpg','photo.jpg',?)", (caption,))


def _caption(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute('SELECT caption FROM photos').fetchone()[0]


def _private_places(path, owner):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('INSERT INTO saved_places(owner,name,normalized_name,latitude,longitude) '
                     'VALUES(?,?,?,?,?)', (owner, 'Home', 'home', 12.5, 44.5))
        conn.execute('INSERT INTO recent_places(owner,latitude,longitude,last_used_at) '
                     'VALUES(?,?,?,?)', (owner, 12.5, 44.5, '2026-01-02T00:00:00Z'))


def test_full_export_omits_private_places_and_incremental_preserves_destination(tmp_path):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    _private_places(source, 'source-owner')
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM saved_places').fetchone() == (0,)
        assert conn.execute('SELECT COUNT(*) FROM recent_places').fetchone() == (0,)
    _private_places(output, 'viewer-owner')
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn:
        assert conn.execute('SELECT owner,name FROM saved_places').fetchall() == [('viewer-owner', 'Home')]
        assert conn.execute('SELECT owner FROM recent_places').fetchall() == [('viewer-owner',)]


@pytest.mark.parametrize('existing', [False, True])
def test_full_export_failure_never_publishes_an_unfinished_copy(tmp_path, monkeypatch, existing):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    _private_places(source, 'private-source')
    if existing:
        _library(output, 'old viewer')
    before = output.read_bytes() if existing else None

    def fail_after_copy(conn):
        assert output.exists() == existing
        if existing:
            assert _caption(output) == 'old viewer'
        raise RuntimeError('injected sanitation failure')

    monkeypatch.setattr(maintenance, '_omit_private_stack_albums', fail_after_copy)
    with pytest.raises(RuntimeError, match='injected sanitation failure'):
        maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
    assert output.exists() == existing
    if existing:
        assert output.read_bytes() == before
    assert not list(tmp_path.glob('.viewer.db.export-*'))


@pytest.mark.parametrize('failure', [RuntimeError, KeyboardInterrupt])
def test_incremental_failure_rolls_back_earlier_metadata_changes(tmp_path, monkeypatch, failure):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source, 'original')
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE photos SET camera_model='new camera'")
    from db import manual_face_export

    def fail_after_metadata(*args):
        raise failure('injected late merge failure')

    monkeypatch.setattr(manual_face_export, 'merge_manual_faces', fail_after_metadata)
    with pytest.raises(failure, match='injected late merge failure'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn:
        assert conn.execute('SELECT camera_model FROM photos').fetchone() == (None,)
        assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)


@pytest.mark.parametrize('alias', ['symlink', 'hardlink'])
def test_export_refuses_alias_of_source_before_any_write(tmp_path, alias):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    try:
        if alias == 'symlink':
            output.symlink_to(source)
        else:
            os.link(source, output)
    except OSError as error:
        pytest.skip(f'{alias} unsupported: {error}')
    before = source.read_bytes()
    with pytest.raises(ValueError, match='same'):
        maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
    assert source.read_bytes() == before


def test_force_export_keeps_the_destination_inode_and_live_wal_connection(tmp_path):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    _library(output, 'old viewer')
    with closing(sqlite3.connect(output)) as reader:
        assert reader.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
        assert reader.execute('SELECT caption FROM photos').fetchone() == ('old viewer',)
        inode = output.stat().st_ino
        maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
        assert output.stat().st_ino == inode
        assert reader.execute('SELECT caption FROM photos').fetchone() == ('source',)
        reader.execute("UPDATE photos SET caption='viewer edit after export'")
        reader.commit()
    assert _caption(output) == 'viewer edit after export'


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_export_refuses_source_named_as_output_companion(tmp_path, existing, suffix):
    output = tmp_path / 'viewer.db'
    source = tmp_path / ('viewer.db' + suffix)
    if existing:
        _library(output, 'previous viewer')
    # Create this last: opening output itself can delete its companion paths.
    _library(source, 'source that must survive')
    before_source = source.read_bytes()
    before_output = output.read_bytes() if existing else None
    with pytest.raises(ValueError, match='companion'):
        maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
    assert source.read_bytes() == before_source
    if existing:
        assert output.read_bytes() == before_output
    else:
        assert not output.exists()
    assert not list(tmp_path.glob('.viewer.db.export-*'))


@pytest.mark.skipif(os.name == 'nt', reason='colon is not a valid Windows filename')
@pytest.mark.parametrize('name', ['file:viewer.db?token=test', 'file:viewer.db#fragment'])
@pytest.mark.parametrize('force', [False, True])
def test_export_treats_uri_looking_output_as_a_literal_filename(tmp_path, monkeypatch, name, force):
    # Some SQLite builds enable URI parsing even without connect(uri=True).
    # Exercise that behavior with real SQLite connections on any local build.
    connect = sqlite3.connect

    def connect_with_uri_default(*args, **kwargs):
        return connect(*args, **(kwargs | {'uri': True}))

    monkeypatch.setattr(sqlite3, 'connect', connect_with_uri_default)
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'source.db'
    output = tmp_path / name
    _library(source, 'before')
    maintenance.export_viewer_db(str(source), name, verbose=False)
    assert _caption(output) == 'before'
    assert not (tmp_path / 'viewer.db').exists()
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE photos SET caption='after'")
    maintenance.export_viewer_db(str(source), name, force=force, verbose=False)
    assert _caption(output) == 'after'
    assert not (tmp_path / 'viewer.db').exists()


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_new_export_refuses_existing_destination_companion_without_deleting_it(tmp_path, suffix):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    companion = Path(str(output) + suffix)
    companion.write_bytes(b'previous private database state')
    before = source.read_bytes()
    with pytest.raises(FileExistsError, match='companion'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert not output.exists()
    assert companion.read_bytes() == b'previous private database state'
    assert source.read_bytes() == before


@pytest.mark.skipif(os.name == 'nt', reason='Windows prevents unlinking a live SQLite main file')
def test_new_export_cannot_publish_into_a_live_orphaned_wal(tmp_path):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source, 'sanitized source snapshot')
    _library(output, 'previous viewer')
    with closing(sqlite3.connect(output)) as keeper:
        keeper.execute('PRAGMA journal_mode=WAL')
        keeper.execute("UPDATE photos SET caption='OLD WAL PRIVATE'")
        keeper.commit()
        output.unlink()
        sidecars = [Path(str(output) + suffix) for suffix in ('-wal', '-shm')]
        before = {path: path.read_bytes() for path in sidecars}
        before_source = source.read_bytes()
        with pytest.raises(FileExistsError, match='companion'):
            maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
        assert not output.exists()
        assert {path: path.read_bytes() for path in sidecars} == before
        assert keeper.execute('SELECT caption FROM photos').fetchone() == ('OLD WAL PRIVATE',)
        assert _caption(source) == 'sanitized source snapshot'
        assert source.read_bytes() == before_source


def test_failed_final_sqlite_backup_preserves_existing_output(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    _library(output, 'old viewer')
    before = output.read_bytes()
    connect = sqlite3.connect

    class FailPublication(sqlite3.Connection):
        def backup(self, target, **kwargs):
            destination = Path(target.execute('PRAGMA database_list').fetchone()[2])
            if destination == output:
                def fail_mid_copy(status, remaining, total):
                    if remaining:
                        raise RuntimeError('injected publication failure')
                kwargs.update(pages=1, progress=fail_mid_copy)
            return super().backup(target, **kwargs)

    def connection(*args, **kwargs):
        return connect(*args, **(kwargs | {'factory': FailPublication}))

    monkeypatch.setattr(maintenance.sqlite3, 'connect', connection)
    with pytest.raises(RuntimeError, match='injected publication failure'):
        maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
    assert output.read_bytes() == before
    assert _caption(output) == 'old viewer'
    assert not list(tmp_path.glob('.viewer.db.export-*'))


def test_incremental_reads_one_source_snapshot_and_reserves_destination_writer(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source, 'first snapshot')
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    from db import manual_face_export
    prepare = manual_face_export.prepare_person_sync

    def change_source_after_first_read(conn):
        columns = prepare(conn)
        with closing(sqlite3.connect(source)) as writer, writer:
            writer.execute("UPDATE photos SET caption='second snapshot'")
        with closing(sqlite3.connect(output, timeout=0)) as viewer_writer:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                viewer_writer.execute("UPDATE photos SET caption='concurrent viewer edit'")
        return columns

    with monkeypatch.context() as patch:
        patch.setattr(manual_face_export, 'prepare_person_sync', change_source_after_first_read)
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert _caption(output) == 'first snapshot'
    assert _caption(source) == 'second snapshot'
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert _caption(output) == 'second snapshot'


@pytest.mark.parametrize('failure', ['decoder', 'encoder'])
def test_incremental_new_thumbnail_failure_rolls_back_and_retry_completes(tmp_path, monkeypatch, failure):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    thumbnail = BytesIO()
    Image.new('RGB', (640, 480), 'blue').save(thumbnail, 'JPEG')
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO photos(path,filename,thumbnail) VALUES('/new.jpg','new.jpg',?)",
                     (b'corrupt JPEG' if failure == 'decoder' else thumbnail.getvalue(),))
    with monkeypatch.context() as patch:
        def failed_resize(*args, **kwargs):
            raise RuntimeError('thumbnail encoder failed')
        if failure == 'encoder':
            patch.setattr(Image.Image, 'thumbnail', failed_resize)
        with pytest.raises((RuntimeError, ValueError), match='thumbnail'):
            maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE path='/new.jpg'").fetchone() == (0,)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE photos SET thumbnail=? WHERE path='/new.jpg'", (thumbnail.getvalue(),))
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn:
        blob = conn.execute("SELECT thumbnail FROM photos WHERE path='/new.jpg'").fetchone()[0]
        assert Image.open(BytesIO(blob)).size == (320, 240)


def test_incremental_invalid_vector_rolls_back_and_retry_completes(tmp_path):
    from db.connection import HAS_SQLITE_VEC, load_sqlite_vec
    if not HAS_SQLITE_VEC:
        pytest.skip('sqlite-vec is unavailable')
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    with closing(sqlite3.connect(source)) as conn, conn:
        load_sqlite_vec(conn)
        conn.execute('CREATE VIRTUAL TABLE photos_vec USING vec0(path TEXT PRIMARY KEY, embedding float[2])')
        conn.execute('INSERT INTO photos_vec(path,embedding) VALUES(?,?)',
                     ('/photo.jpg', struct.pack('ff', 1, 0)))
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO photos(path,filename,clip_embedding) VALUES('/new.jpg','new.jpg',?)",
                     (struct.pack('fff', 0, 1, 0),))
    with pytest.raises(sqlite3.DatabaseError, match='photos_vec'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn:
        load_sqlite_vec(conn)
        assert conn.execute('SELECT path FROM photos').fetchall() == [('/photo.jpg',)]
        assert conn.execute('SELECT path FROM photos_vec').fetchall() == [('/photo.jpg',)]
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("UPDATE photos SET clip_embedding=? WHERE path='/new.jpg'", (struct.pack('ff', 0, 1),))
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn:
        load_sqlite_vec(conn)
        assert conn.execute("SELECT COUNT(*) FROM photos WHERE path='/new.jpg'").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM photos_vec WHERE path='/new.jpg'").fetchone() == (1,)


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_export_refuses_source_sqlite_companion_paths(tmp_path, suffix):
    source = tmp_path / 'source.db'
    _library(source)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("UPDATE photos SET caption='pending WAL write'")
        with pytest.raises(ValueError, match='same'):
            maintenance.export_viewer_db(str(source), str(source) + suffix, force=True, verbose=False)
        conn.commit()
    assert _caption(source) == 'pending WAL write'


@pytest.mark.parametrize('existing', [False, True])
def test_export_disk_preflight_preserves_public_destination(tmp_path, monkeypatch, existing):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    if existing:
        _library(output, 'old viewer')
    before = output.read_bytes() if existing else None
    monkeypatch.setattr(maintenance, 'check_disk_space', lambda *args: (False, 0, 100))
    with pytest.raises(RuntimeError, match='free space'):
        maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
    assert output.exists() == existing
    if existing:
        assert output.read_bytes() == before


def test_new_export_on_filesystem_without_hardlinks_fails_cleanly(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    before = source.read_bytes()

    def unsupported(*args):
        raise OSError('hardlinks unsupported')

    monkeypatch.setattr(maintenance.os, 'link', unsupported)
    with pytest.raises(OSError, match='filesystem must support hard links'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert not output.exists()
    assert source.read_bytes() == before
    assert not list(tmp_path.glob('.viewer.db.export-*'))


def test_invalid_full_export_fails_foreign_key_validation_before_publication(tmp_path):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    _library(output, 'old viewer')
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding) VALUES('/missing.jpg',0,?)", (b'',))
    before = output.read_bytes()
    with pytest.raises(sqlite3.IntegrityError, match='foreign key validation'):
        maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
    assert output.read_bytes() == before
    assert _caption(output) == 'old viewer'
    assert not list(tmp_path.glob('.viewer.db.export-*'))
