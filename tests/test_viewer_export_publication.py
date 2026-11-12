"""Viewer exports publish complete snapshots and preserve private destination state."""

import os
import sqlite3
import stat
import struct
from contextlib import closing
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

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


def _jpeg(color, size=(640, 480)):
    buffer = BytesIO()
    Image.new('RGB', size, color).save(buffer, 'JPEG')
    return buffer.getvalue()


def _add_photo(path, photo, thumbnail):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO photos(path,filename,thumbnail) VALUES(?,?,?)",
                     (photo, photo.lstrip('/'), thumbnail))


def _exported_thumbnail(path, photo):
    with closing(sqlite3.connect(path)) as conn:
        blob = conn.execute('SELECT thumbnail FROM photos WHERE path=?', (photo,)).fetchone()[0]
    return Image.open(BytesIO(blob)).convert('RGB')


def _photo_paths(path):
    with closing(sqlite3.connect(path)) as conn:
        return {row[0] for row in conn.execute('SELECT path FROM photos')}


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


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')
def test_published_databases_take_the_mode_sqlite_gives_a_new_database(tmp_path):
    # SQLite creates files 0644 & ~umask, as a direct connect to the output did.
    source, output, replaced = tmp_path / 'source.db', tmp_path / 'viewer.db', tmp_path / 'replaced.db'
    _library(source)
    replaced.write_bytes(b'not a database')
    previous = os.umask(0o002)
    try:
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
        maintenance.export_viewer_db(str(source), str(replaced), force=True, verbose=False)
        backup = maintenance.backup_database(str(source), keep=3, verbose=False)
    finally:
        os.umask(previous)
    for published in (output, replaced, Path(backup)):
        assert stat.S_IMODE(published.stat().st_mode) == 0o644, published


@pytest.mark.parametrize('content', ['not_sqlite', 'header_then_garbage', 'truncated_database'])
def test_force_export_replaces_a_file_sqlite_cannot_open(tmp_path, content):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    if content == 'not_sqlite':
        output.write_bytes(b'not a database' * 100)
    elif content == 'header_then_garbage':
        output.write_bytes(b'SQLite format 3\x00' + os.urandom(8192))
    else:
        _library(output, 'old')
        output.write_bytes(output.read_bytes()[:3000])
    maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
    assert _caption(output) == 'source'
    assert not list(tmp_path.glob('.viewer.db.export-*'))


def test_force_export_keeps_an_output_another_connection_has_locked(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    _library(output, 'old')
    connect = sqlite3.connect
    monkeypatch.setattr(maintenance.sqlite3, 'connect', lambda *a, **kw: connect(*a, **(kw | {'timeout': 0.1})))
    with closing(connect(output, isolation_level=None)) as holder:
        holder.execute('BEGIN EXCLUSIVE')
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            maintenance.export_viewer_db(str(source), str(output), force=True, verbose=False)
        holder.execute('ROLLBACK')
    assert _caption(output) == 'old'


def test_export_cleanup_failure_neither_hides_nor_causes_an_error(tmp_path, monkeypatch, caplog):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    monkeypatch.setattr(maintenance.shutil, 'rmtree', lambda path, ignore_errors=False: None)
    with caplog.at_level('WARNING', logger='facet.db_maintenance'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert _caption(output) == 'source'
    assert 'Could not remove temporary directory' in caplog.text


def test_incremental_downsizes_new_thumbnails_before_reserving_the_viewer_writer(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    _add_photo(source, '/new.jpg', _jpeg('blue'))
    resize = Image.Image.thumbnail
    viewer_writes = []

    def resize_while_the_viewer_writes(image, *args, **kwargs):
        with closing(sqlite3.connect(output, timeout=0)) as viewer, viewer:
            viewer.execute("UPDATE photos SET star_rating=4 WHERE path='/photo.jpg'")
        viewer_writes.append('committed')
        return resize(image, *args, **kwargs)

    monkeypatch.setattr(Image.Image, 'thumbnail', resize_while_the_viewer_writes)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert viewer_writes == ['committed']
    assert _exported_thumbnail(output, '/new.jpg').size == (320, 240)


def test_incremental_prepares_thumbnails_only_up_to_the_temp_cap(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    _add_photo(source, '/a.jpg', _jpeg('blue'))
    _add_photo(source, '/b.jpg', _jpeg('green'))
    monkeypatch.setattr(maintenance, '_PREPARED_THUMBNAIL_CAP', 1)
    monkeypatch.setattr(maintenance, '_EXPORT_BATCH_SIZE', 1)
    resize = Image.Image.thumbnail
    viewer_writes = []

    def resize_while_the_viewer_writes(image, *args, **kwargs):
        try:
            with closing(sqlite3.connect(output, timeout=0)) as viewer, viewer:
                viewer.execute("UPDATE photos SET star_rating=4 WHERE path='/photo.jpg'")
            viewer_writes.append('committed')
        except sqlite3.OperationalError:
            viewer_writes.append('locked')
        return resize(image, *args, **kwargs)

    monkeypatch.setattr(Image.Image, 'thumbnail', resize_while_the_viewer_writes)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    # The first is prepared before the writer is reserved; the cap leaves the
    # second to be downsized under the lock.
    assert viewer_writes == ['committed', 'locked']
    assert _exported_thumbnail(output, '/b.jpg').size == (320, 240)


def test_incremental_ignores_prepared_thumbnails_the_source_no_longer_holds(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    _add_photo(source, '/changed.jpg', _jpeg('blue'))
    check = maintenance._check_export_space

    def change_source_after_preparation(*args):
        with closing(sqlite3.connect(source)) as writer, writer:
            writer.execute("UPDATE photos SET thumbnail=? WHERE path='/changed.jpg'", (_jpeg('red'),))
        _add_photo(source, '/later.jpg', _jpeg('green'))
        return check(*args)

    monkeypatch.setattr(maintenance, '_check_export_space', change_source_after_preparation)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    red, green, blue = _exported_thumbnail(output, '/changed.jpg').getpixel((160, 120))
    assert red > 200 and blue < 60
    assert _exported_thumbnail(output, '/later.jpg').size == (320, 240)


def test_incremental_space_budget_counts_the_viewer_database_not_the_source(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(source)) as conn, conn:
        conn.execute('CREATE TABLE scan_only(blob BLOB)')
        conn.executemany('INSERT INTO scan_only VALUES(randomblob(65536))', [()] * 64)
    room = 2 * output.stat().st_size
    assert room < source.stat().st_size
    monkeypatch.setattr(maintenance.shutil, 'disk_usage', lambda path: SimpleNamespace(free=room))
    _add_photo(source, '/new.jpg', None)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert '/new.jpg' in _photo_paths(output)
    monkeypatch.setattr(maintenance.shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    _add_photo(source, '/refused.jpg', None)
    with pytest.raises(RuntimeError, match='free space'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert '/refused.jpg' not in _photo_paths(output)


def test_full_export_refuses_an_output_created_while_it_was_built(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    prepare = maintenance._prepare_full_viewer_copy

    def competitor_creates_output(*args):
        _library(output, 'competitor')
        return prepare(*args)

    monkeypatch.setattr(maintenance, '_prepare_full_viewer_copy', competitor_creates_output)
    with pytest.raises(FileExistsError, match='Output appeared during export'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert _caption(output) == 'competitor'
    assert not list(tmp_path.glob('.viewer.db.export-*'))


def test_full_export_never_links_over_an_output_created_at_publication(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    link = os.link

    def competitor_wins_the_race(staging, destination):
        _library(output, 'competitor')
        return link(staging, destination)

    monkeypatch.setattr(maintenance.os, 'link', competitor_wins_the_race)
    with pytest.raises(FileExistsError):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert _caption(output) == 'competitor'
    assert not list(tmp_path.glob('.viewer.db.export-*'))


def test_incremental_refuses_a_viewer_database_that_fails_its_integrity_check(tmp_path, monkeypatch):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    _add_photo(source, '/new.jpg', None)
    connect = sqlite3.connect

    class CorruptViewer(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == 'PRAGMA main.quick_check':
                sql = "SELECT 'row 7 missing from index'"
            return super().execute(sql, *args)

    monkeypatch.setattr(maintenance.sqlite3, 'connect',
                        lambda *a, **kw: connect(*a, **(kw | {'factory': CorruptViewer})))
    prepared = []
    monkeypatch.setattr(maintenance, '_prepare_new_thumbnails', lambda *args: prepared.append(args) or 0)
    with pytest.raises(sqlite3.DatabaseError, match='Viewer export validation failed'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    monkeypatch.undo()
    assert not prepared, 'the integrity check must refuse before any thumbnail work'
    assert _photo_paths(output) == {'/photo.jpg'}


def test_incremental_foreign_key_violation_rolls_back_the_sync(tmp_path):
    source, output = tmp_path / 'source.db', tmp_path / 'viewer.db'
    _library(source)
    maintenance.export_viewer_db(str(source), str(output), verbose=False)
    with closing(sqlite3.connect(output)) as conn, conn:
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding) VALUES('/missing.jpg',0,?)", (b'',))
    _add_photo(source, '/new.jpg', None)
    with pytest.raises(sqlite3.IntegrityError, match='foreign key validation'):
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    assert _photo_paths(output) == {'/photo.jpg'}


def _orphan_tag(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("INSERT INTO photo_tags (photo_path, tag) VALUES ('/gone.jpg', 'sky')")


@pytest.mark.parametrize('incremental', [True, False], ids=['incremental', 'full'])
def test_orphaned_row_names_the_table_and_the_databases_to_inspect(tmp_path, incremental):
    library = tmp_path / 'my library'
    library.mkdir()
    source, output = library / 'source.db', library / 'viewer.db'
    _library(source)
    if incremental:
        maintenance.export_viewer_db(str(source), str(output), verbose=False)
    _orphan_tag(source)
    with pytest.raises(sqlite3.IntegrityError) as exc:
        maintenance.export_viewer_db(str(source), str(output), force=not incremental, verbose=False)
    message = str(exc.value)
    assert 'foreign key validation failed: rows in photo_tags reference' in message
    assert f"--db '{source}'" in message
    assert (f"--db '{output}'" in message) == incremental
