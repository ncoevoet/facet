"""Real CLI effects: previews and invalid combinations must leave data alone."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import shutil
import subprocess
import sys

import pytest
from PIL import Image

from db.schema import init_database
from facet import LibraryLock

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def library(tmp_path):
    db = tmp_path / 'library.db'
    init_database(str(db))
    config = tmp_path / 'config.json'
    config.write_text('{"narrative_moments":{"enabled":false},"junk_sweep":{"enabled":false}}',
                      encoding='utf-8')
    photo = tmp_path / 'photo.jpg'
    Image.new('RGB', (8, 8), (80, 120, 160)).save(photo)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('INSERT INTO photos(path,filename,tags,star_rating,face_count,is_silhouette) '
                     'VALUES (?,?,?,3,0,1)', (str(photo), photo.name, 'safety-check'))
        conn.commit()
        conn.execute('PRAGMA journal_mode=DELETE')
    return db, config, photo


def run_cli(library, script, *args):
    db, config, _ = library
    env = {**os.environ, 'DB_PATH': str(db), 'FACET_CONFIG': str(config)}
    return subprocess.run([sys.executable, str(ROOT / script), '--db', str(db), *args],
                          cwd=db.parent, env=env, capture_output=True, text=True,
                          encoding='utf-8', timeout=60)


def snapshot(library):
    return {path.name: path.read_bytes() for path in library[0].parent.iterdir() if path.is_file()}


def test_sidecar_dry_run_refuses_before_writing_but_normal_export_works(library):
    before = snapshot(library)
    proc = run_cli(library, 'facet.py', '--export-sidecars', '--dry-run')
    assert snapshot(library) == before
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert '--export-sidecars' in proc.stderr and 'no dry-run' in proc.stderr
    proc = run_cli(library, 'facet.py', '--export-sidecars')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sidecar = Path(str(library[2]) + '.xmp')
    assert sidecar.exists() and 'safety-check' in sidecar.read_text(encoding='utf-8')
    assert library[2].read_bytes() == before['photo.jpg']


def test_combined_database_commands_cannot_bypass_library_lock(library):
    db = library[0]
    with LibraryLock(str(db), kind='scan'):
        before = snapshot(library)
        proc = run_cli(library, 'database.py', '--cleanup-missing-photos', '--dry-run', '--migrate-tags')
        assert snapshot(library) == before
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert 'not allowed with argument' in proc.stderr
        normal = run_cli(library, 'database.py', '--migrate-tags')
        assert normal.returncode == 75, normal.stdout + normal.stderr
    proc = run_cli(library, 'database.py', '--migrate-tags')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with closing(sqlite3.connect(db)) as conn, conn:
        assert conn.execute('SELECT tag FROM photo_tags').fetchall() == [('safety-check',)]


@pytest.mark.parametrize('flag', [
    '--detect-moments', '--recompute-moments', '--detect-junk', '--recompute-junk',
    '--recompute-silhouette',
])
def test_supported_previews_preserve_database_and_config_bytes(library, flag):
    before = snapshot(library)
    proc = run_cli(library, 'facet.py', flag, '--dry-run')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert snapshot(library) == before
    if flag == '--recompute-silhouette':
        proc = run_cli(library, 'facet.py', flag)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        with closing(sqlite3.connect(library[0])) as conn, conn:
            assert conn.execute('SELECT is_silhouette FROM photos').fetchone() == (0,)


@pytest.mark.parametrize('args', [
    ('--force',), ('--force-export',), ('--role', 'user'), ('--display-name', 'Test'),
    ('--user', 'alice'), ('--keep', '3'), ('--info', '--backup'),
    ('--relink-photos', '--info'), ('--relink-photo',),
    ('--add-user', ''), ('--export-viewer-db', ''),
])
def test_database_orphan_modifiers_and_conflicting_operations_do_not_initialize(library, args):
    before = snapshot(library)
    proc = run_cli(library, 'database.py', *args)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert snapshot(library) == before


def test_cleanup_preview_stays_read_only_and_normal_cleanup_removes_missing_rows(library):
    db, _, _ = library
    missing = db.parent / 'missing.jpg'
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('INSERT INTO photos(path,filename) VALUES (?,?)', (str(missing), missing.name))
    before = snapshot(library)
    proc = run_cli(library, 'database.py', '--cleanup-missing-photos', '--dry-run')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert snapshot(library) == before
    proc = run_cli(library, 'database.py', '--cleanup-missing-photos')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with closing(sqlite3.connect(db)) as conn, conn:
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE path=?', (str(missing),)).fetchone() == (0,)


def test_duplicate_refusal_preserves_rows_and_normal_command_groups_them(library):
    db, _, photo = library
    other = photo.with_name('second.jpg')
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('UPDATE photos SET phash=?,aggregate=8', ('1234567890abcdef',))
        conn.execute('INSERT INTO photos(path,filename,phash,aggregate) VALUES (?,?,?,6)',
                     (str(other), other.name, '1234567890abcdef'))
    before = snapshot(library)
    proc = run_cli(library, 'facet.py', '--detect-duplicates', '--dry-run')
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert snapshot(library) == before
    proc = run_cli(library, 'facet.py', '--detect-duplicates')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with closing(sqlite3.connect(db)) as conn, conn:
        rows = conn.execute('SELECT duplicate_group_id,is_duplicate_lead FROM photos ORDER BY aggregate DESC').fetchall()
    assert rows[0][0] is not None and rows[0][0] == rows[1][0]
    assert [row[1] for row in rows] == [1, 0]


@pytest.mark.parametrize('flag', ['--export-sidecars', '--detect-duplicates', '--watch', '--extract-gps'])
def test_unsupported_preview_does_not_create_database(library, flag):
    library[0].unlink()
    before = snapshot(library)
    proc = run_cli(library, 'facet.py', flag, '--dry-run')
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert snapshot(library) == before


@pytest.mark.parametrize('flag', [
    '--detect-moments', '--recompute-moments', '--detect-junk', '--recompute-junk',
    '--recompute-silhouette',
])
def test_native_previews_leave_released_schema_unchanged(library, flag):
    db, _, photo = library
    db.unlink()
    released = ROOT / 'tests/fixtures/photo_stacks_v1_23_1_schema.sql'
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.executescript(released.read_text(encoding='utf-8'))
        conn.execute('INSERT INTO photos(path,filename,face_count,is_silhouette) VALUES (?,?,0,1)',
                     (str(photo), photo.name))
    before = snapshot(library)
    proc = run_cli(library, 'facet.py', flag, '--dry-run')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert snapshot(library) == before


@pytest.mark.skipif(shutil.which('exiftool') is None, reason='requires ExifTool')
@pytest.mark.parametrize('flag,initial', [('--extract-gps', None), ('--rescan-gps', 45.0)])
def test_gps_refusal_preserves_coordinates_and_normal_command_updates(library, flag, initial):
    db, _, photo = library
    exif = subprocess.run(['exiftool', '-overwrite_original', '-GPSLatitude=10',
                           '-GPSLatitudeRef=N', '-GPSLongitude=20', '-GPSLongitudeRef=E',
                           str(photo)], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert exif.returncode == 0, exif.stdout + exif.stderr
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('UPDATE photos SET gps_latitude=?,gps_longitude=?,gps_manually_set=0',
                     (initial, initial))
    before = snapshot(library)
    proc = run_cli(library, 'facet.py', flag, '--dry-run')
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert snapshot(library) == before
    proc = run_cli(library, 'facet.py', flag)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with closing(sqlite3.connect(db)) as conn, conn:
        assert conn.execute('SELECT gps_latitude,gps_longitude FROM photos').fetchone() == (10.0, 20.0)
    assert photo.read_bytes() == before[photo.name]
