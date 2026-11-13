"""--backfill-exif-meta: fills NULL file_size rows, leaves unreadable ones NULL, is resumable."""
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from PIL import Image

from db.schema import init_database

ROOT = Path(__file__).resolve().parents[1]
EXIFTOOL = shutil.which('exiftool')
pytestmark = pytest.mark.skipif(EXIFTOOL is None, reason='exiftool not installed')


@pytest.fixture
def library(tmp_path):
    db = tmp_path / 'library.db'
    init_database(str(db))
    photo = tmp_path / 'a.jpg'
    Image.new('RGB', (16, 16), (1, 2, 3)).save(photo)
    subprocess.run([EXIFTOOL, '-overwrite_original', '-n', '-EXIF:Flash=1', '-EXIF:WhiteBalance=1',
                    '-EXIF:MeteringMode=5', '-EXIF:ExposureCompensation=0.7', '-Artist=Ann',
                    '-Copyright=(c) 2024', str(photo)], check=True, capture_output=True)
    missing = tmp_path / 'gone.jpg'
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.executemany('INSERT INTO photos(path, filename) VALUES (?, ?)',
                         [(str(photo), photo.name), (str(missing), missing.name)])
        conn.commit()
    return db, photo, missing


def run_cli(db, *args):
    env = {**os.environ, 'DB_PATH': str(db)}
    return subprocess.run([sys.executable, str(ROOT / 'facet.py'), '--db', str(db), *args],
                          cwd=db.parent, env=env, capture_output=True, text=True,
                          encoding='utf-8', timeout=120)


def _rows(db):
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        return {r['path']: dict(r) for r in conn.execute('SELECT * FROM photos')}


def test_backfill_fills_null_rows_and_counts_unreadable(library):
    db, photo, missing = library
    proc = run_cli(db, '--backfill-exif-meta')
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    rows = _rows(db)
    filled = rows[str(photo)]
    assert filled['file_size'] == photo.stat().st_size
    assert (filled['flash'], filled['white_balance'], filled['metering_mode']) == (1, 1, 5)
    assert filled['exposure_compensation'] == 0.7
    assert (filled['artist'], filled['copyright']) == ('Ann', '(c) 2024')
    assert rows[str(missing)]['file_size'] is None
    assert 'Updated EXIF metadata for 1/2' in out
    assert '1 photos could not be read' in out and '--cleanup-missing-photos' in out


def test_backfill_rerun_updates_only_the_unread_rows(library):
    db, photo, _ = library
    assert run_cli(db, '--backfill-exif-meta').returncode == 0
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('UPDATE photos SET artist = ? WHERE path = ?', ('edited', str(photo)))
        conn.commit()
    proc = run_cli(db, '--backfill-exif-meta')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'Updated EXIF metadata for 0/1' in proc.stdout + proc.stderr
    assert _rows(db)[str(photo)]['artist'] == 'edited'


def test_backfill_refuses_dry_run(library):
    db, _, _ = library
    proc = run_cli(db, '--backfill-exif-meta', '--dry-run')
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert '--backfill-exif-meta' in proc.stderr
    assert _rows(db)[str(library[1])]['file_size'] is None


def test_backfill_refuses_without_exiftool(library, tmp_path):
    db, _, _ = library
    env = {**os.environ, 'DB_PATH': str(db), 'PATH': str(tmp_path / 'empty')}
    proc = subprocess.run([sys.executable, str(ROOT / 'facet.py'), '--db', str(db), '--backfill-exif-meta'],
                          cwd=db.parent, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0
    assert 'needs exiftool' in proc.stdout + proc.stderr


def test_backfill_unreadable_file_does_not_sink_its_chunk(library, tmp_path):
    # A zero-byte file makes exiftool exit 1 while still printing JSON for the
    # rest of the chunk; the readable photo beside it must still be filled.
    db, photo, _ = library
    broken = tmp_path / 'broken.jpg'
    broken.write_bytes(b'')
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('INSERT INTO photos(path, filename) VALUES (?, ?)', (str(broken), broken.name))
        conn.commit()
    proc = run_cli(db, '--backfill-exif-meta')
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    rows = _rows(db)
    assert rows[str(photo)]['file_size'] == photo.stat().st_size
    assert rows[str(broken)]['file_size'] is None
    assert 'Updated EXIF metadata for 1/3' in out
