"""scripts/rewrite_db_paths.py: move a Docker-scanned library to Windows paths."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from db.schema import init_database

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'rewrite_db_paths.py'
SRC = '/data/photos'
DST = r'\\NAS\Photos'


def _run(db, *extra, src=SRC, dst=DST, check=True):
    return subprocess.run([sys.executable, str(SCRIPT), str(db), src, dst, *extra],
                          capture_output=True, text=True, check=check)


@pytest.fixture
def library(tmp_path):
    db = tmp_path / 'library.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO photos (path, filename) VALUES (?, ?)', [
            ('/data/photos/2024/trip/a.jpg', 'a.jpg'),
            ('/data/photos/b.jpg', 'b.jpg'),
            ('/data/photos-old/c.jpg', 'c.jpg'),  # shares the prefix text, not the folder
            ('/elsewhere/d.jpg', 'd.jpg'),
        ])
        conn.execute("INSERT INTO faces (photo_path, face_index, embedding) VALUES (?, 0, x'00')",
                     ('/data/photos/2024/trip/a.jpg',))
        album = conn.execute(
            'INSERT INTO albums (name, cover_photo_path, smart_filter_json) VALUES (?, ?, ?)',
            ('Trip', '/data/photos/b.jpg',
             json.dumps({'path_prefix': '/data/photos/2024', 'tags': ['beach']}))).lastrowid
        conn.execute('INSERT INTO album_photos (album_id, photo_path) VALUES (?, ?)',
                     (album, '/data/photos/2024/trip/a.jpg'))
        conn.execute('INSERT INTO scan_runs (args_json) VALUES (?)',
                     (json.dumps({'directories': ['/data/photos/2024'], 'force': False}),))
    return db


def _paths(db, sql):
    with sqlite3.connect(db) as conn:
        return [row[0] for row in conn.execute(sql)]


def test_rewrites_every_path_column_under_the_prefix_only(library):
    out = _run(library).stdout
    assert sorted(_paths(library, 'SELECT path FROM photos')) == sorted([
        r'\\NAS\Photos\2024\trip\a.jpg',
        r'\\NAS\Photos\b.jpg',
        '/data/photos-old/c.jpg',
        '/elsewhere/d.jpg',
    ])
    assert _paths(library, 'SELECT photo_path FROM faces') == [r'\\NAS\Photos\2024\trip\a.jpg']
    assert _paths(library, 'SELECT photo_path FROM album_photos') == [r'\\NAS\Photos\2024\trip\a.jpg']
    assert _paths(library, 'SELECT cover_photo_path FROM albums') == [r'\\NAS\Photos\b.jpg']
    assert 'integrity: ok' in out
    assert '| foreign keys: 0 violations' in out
    assert out.rstrip().endswith('photos left on old prefix: 0')


def test_rewrites_paths_inside_json_columns(library):
    _run(library)
    smart = json.loads(_paths(library, 'SELECT smart_filter_json FROM albums')[0])
    assert smart == {'path_prefix': r'\\NAS\Photos\2024', 'tags': ['beach']}
    args = json.loads(_paths(library, 'SELECT args_json FROM scan_runs')[0])
    assert args == {'directories': [r'\\NAS\Photos\2024'], 'force': False}


def test_rebuilds_fts_on_the_new_paths(library):
    _run(library)
    with sqlite3.connect(library) as conn:
        indexed = {row[0] for row in conn.execute('SELECT path FROM photos_fts')}
    assert r'\\NAS\Photos\b.jpg' in indexed
    assert '/data/photos/b.jpg' not in indexed


def test_second_run_changes_nothing(library):
    _run(library)
    before = _paths(library, 'SELECT path FROM photos ORDER BY rowid')
    out = _run(library).stdout
    assert _paths(library, 'SELECT path FROM photos ORDER BY rowid') == before
    assert 'photos.path' not in out


def test_separator_can_stay_forward_slash(library):
    _run(library, '--sep', '/')
    assert r'\\NAS\Photos/2024/trip/a.jpg' in _paths(library, 'SELECT path FROM photos')


def test_dry_run_reports_and_writes_nothing(library):
    before = _paths(library, 'SELECT path FROM photos ORDER BY rowid')
    out = _run(library, '--dry-run').stdout
    assert 'photos.path: 2' in out
    assert 'dry run: nothing written' in out
    assert _paths(library, 'SELECT path FROM photos ORDER BY rowid') == before
    assert not list(library.parent.glob('library.db.before-rewrite-*'))


def test_backs_up_the_database_first(library):
    out = _run(library).stdout
    backups = list(library.parent.glob('library.db.before-rewrite-*'))
    assert len(backups) == 1 and f'backup: {backups[0]}' in out
    assert '/data/photos/b.jpg' in _paths(backups[0], 'SELECT path FROM photos')


def test_trailing_separators_never_double(library):
    _run(library, src='/data/photos/', dst=DST + '\\')
    assert r'\\NAS\Photos\b.jpg' in _paths(library, 'SELECT path FROM photos')


def test_runs_in_reverse_from_a_windows_prefix(library):
    _run(library)
    out = _run(library, src=DST, dst=SRC).stdout
    assert sorted(_paths(library, 'SELECT path FROM photos')) == sorted([
        '/data/photos/2024/trip/a.jpg', '/data/photos/b.jpg', '/data/photos-old/c.jpg', '/elsewhere/d.jpg'])
    assert out.rstrip().endswith('photos left on old prefix: 0')


def test_separator_follows_a_posix_target(library):
    _run(library, dst='/srv/photos')
    assert '/srv/photos/2024/trip/a.jpg' in _paths(library, 'SELECT path FROM photos')


def test_matching_is_exact_not_like(library):
    with sqlite3.connect(library) as conn:
        conn.executemany('INSERT INTO photos (path, filename) VALUES (?, ?)', [
            ('/DATA/photos/e.jpg', 'e.jpg'),        # LIKE ignores case
            ('/dataXphotos/f.jpg', 'f.jpg'),        # an unescaped _ or % would match
        ])
    out = _run(library, src='/data_photos').stdout
    assert 'nothing stored under /data_photos' in out
    assert {'/DATA/photos/e.jpg', '/dataXphotos/f.jpg'} <= set(_paths(library, 'SELECT path FROM photos'))


def test_a_path_already_under_the_new_prefix_changes_nothing(library):
    with sqlite3.connect(library) as conn:
        conn.execute('INSERT INTO photos (path, filename) VALUES (?, ?)', (r'\\NAS\Photos\b.jpg', 'b.jpg'))
    before = _paths(library, 'SELECT path FROM photos ORDER BY rowid')
    result = _run(library, '--no-backup', check=False)
    assert result.returncode != 0
    assert 'already exist under the new prefix' in result.stderr
    assert 'Traceback' not in result.stderr
    assert _paths(library, 'SELECT path FROM photos ORDER BY rowid') == before


@pytest.mark.parametrize('src,dst', [('/data/photos', '/data/photos/lib'), ('/data/photos/lib', '/data/photos')])
@pytest.mark.parametrize('flags', [(), ('--dry-run',)])
def test_nested_prefixes_are_refused_and_nothing_changes(library, src, dst, flags):
    before = _paths(library, 'SELECT path FROM photos ORDER BY rowid')
    result = _run(library, *flags, src=src, dst=dst, check=False)
    assert result.returncode == 2
    assert 'inside the other' in result.stderr
    assert _paths(library, 'SELECT path FROM photos ORDER BY rowid') == before


def test_stacks_move_and_skipped_suggestions_stay_skipped(library):
    from db.stack_suggestions import dismiss, suggestion_key
    old = ['/data/photos/2024/trip/a.jpg', '/data/photos/b.jpg']
    new = [r'\\NAS\Photos\2024\trip\a.jpg', r'\\NAS\Photos\b.jpg']
    with sqlite3.connect(library) as conn:
        conn.execute("INSERT INTO photo_stacks (id, owner, cover_path, revision) VALUES ('s1', '', ?, 1)", (old[0],))
        conn.executemany("INSERT INTO photo_stack_members (stack_id, owner, photo_path, position) VALUES ('s1', '', ?, ?)",
                         [(path, i) for i, path in enumerate(old)])
        dismiss(conn, '', 'burst', old)
    out = _run(library).stdout
    assert _paths(library, 'SELECT cover_path FROM photo_stacks') == [new[0]]
    assert sorted(_paths(library, 'SELECT photo_path FROM photo_stack_members')) == sorted(new)
    # The key hashes the member paths: unchanged, the skipped suggestion would come back.
    assert _paths(library, 'SELECT DISTINCT key FROM stack_suggestion_dismissals') == [suggestion_key('burst', new)]
    assert 'stack_suggestion_dismissals: 1 skipped suggestions re-keyed' in out


def test_a_locked_database_is_refused_cleanly(library):
    holder = sqlite3.connect(library, isolation_level=None)
    holder.execute('BEGIN IMMEDIATE')
    try:
        done = _run(library, '--no-backup', check=False)
    finally:
        holder.execute('ROLLBACK')
        holder.close()
    assert done.returncode == 1
    assert 'stop the viewer' in done.stderr and 'Traceback' not in done.stderr
    assert _paths(library, "SELECT count(*) FROM photos WHERE path LIKE '/data/photos/%'") == [2]
