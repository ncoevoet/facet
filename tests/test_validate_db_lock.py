"""Repair is a library job, including the interactive path."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from db.schema import init_database
from facet import LibraryLock, LibraryLockError


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def library(tmp_path):
    db = tmp_path / 'repair.db'
    init_database(str(db))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photos(path,filename,face_count,is_blink) VALUES('/photo.jpg','photo.jpg',0,1)")
    config = tmp_path / 'config.json'
    config.write_text('{}', encoding='utf-8')
    return db, config


def _run(library, *flags, answers='y\nf\n'):
    db, config = library
    return subprocess.run(
        [sys.executable, str(ROOT / 'validate_db.py'), '--db', str(db), *flags],
        cwd=db.parent, env={**os.environ, 'FACET_CONFIG': str(config)},
        input=answers, capture_output=True, text=True, encoding='utf-8', timeout=30,
    )


def _blink(db):
    with sqlite3.connect(db) as conn:
        return conn.execute('SELECT is_blink FROM photos').fetchone()[0]


@pytest.mark.parametrize('flags', [(), ('--auto-fix',)])
def test_repairs_refuse_a_busy_library_and_preserve_rows(library, flags):
    db, _ = library
    with LibraryLock(str(db), kind='scan'):
        result = _run(library, *flags)
    assert result.returncode == 75, result.stdout + result.stderr
    assert _blink(db) == 1


@pytest.mark.parametrize('flags', [(), ('--auto-fix',)])
def test_repairs_succeed_and_release_the_library(library, flags):
    db, _ = library
    result = _run(library, *flags)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _blink(db) == 0
    with LibraryLock(str(db), kind='scan'):
        pass


@pytest.mark.parametrize('flags', [(), ('--auto-fix',)])
def test_unusable_repair_lock_is_a_failure_not_a_busy_library(library, flags):
    db, _ = library
    (db.parent / '.facet_cache').write_text('not a directory', encoding='utf-8')
    result = _run(library, *flags)
    assert result.returncode == 1, result.stdout + result.stderr
    assert _blink(db) == 1


@pytest.mark.parametrize('flags,answers', [(('--report-only',), ''), ((), 'n\n')])
def test_reporting_and_declining_do_not_require_the_repair_lock(library, flags, answers):
    db, _ = library
    with LibraryLock(str(db), kind='scan'):
        result = _run(library, *flags, answers=answers)
    # The point is that neither path takes the repair lock, and the row survives
    # untouched. Neither fixes anything, so under the exit-status contract the
    # reported issue still stands: exit 3, distinct from a runtime failure.
    assert result.returncode == 3, result.stdout + result.stderr
    assert _blink(db) == 1


def test_confirmation_rechecks_issues_before_repair(library, monkeypatch):
    import validate_db

    db, _ = library
    monkeypatch.setattr(sys, 'argv', ['validate_db.py', '--db', str(db)])
    prompts = []

    def confirm(prompt):
        prompts.append(prompt)
        assert len(prompts) == 1, 'the already-fixed issue must not be offered again'
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE photos SET is_blink=0')
        return 'y'

    monkeypatch.setattr('builtins.input', confirm)
    assert validate_db.main() == 0
    assert _blink(db) == 0
    with LibraryLock(str(db), kind='scan'):
        pass


@pytest.mark.parametrize('flags', [(), ('--auto-fix',)])
@pytest.mark.parametrize('new_issues', [False, True])
def test_repair_exit_status_uses_post_repair_database(library, flags, new_issues):
    db, _ = library
    with sqlite3.connect(db) as conn:
        # Repairing face_count can expose blink/metric inconsistencies. Clearing
        # metrics can also resolve an initially unfixable score-range finding.
        conn.execute('UPDATE photos SET face_count=?, face_quality=?, eye_sharpness=5, is_blink=?',
                     (1 if new_issues else 0, 5 if new_issues else 11, 1 if new_issues else 0))

    repaired = _run(library, *flags)
    reported = _run(library, '--report-only')

    expected = 3 if new_issues else 0
    assert repaired.returncode == expected, repaired.stdout + repaired.stderr
    assert reported.returncode == expected, reported.stdout + reported.stderr
    with sqlite3.connect(db) as conn:
        face_count, quality = conn.execute('SELECT face_count, face_quality FROM photos').fetchone()
    assert face_count == 0
    assert quality == (5 if new_issues else 0)
    with LibraryLock(str(db), kind='scan'):
        pass


@pytest.mark.parametrize('check_fails', [False, True])
def test_post_repair_check_holds_lock_and_releases_it_on_error(library, monkeypatch, check_fails):
    import validate_db
    from validation import DatabaseValidator

    db, _ = library
    monkeypatch.setattr(sys, 'argv', ['validate_db.py', '--db', str(db), '--auto-fix'])
    original = DatabaseValidator.run_all_checks
    rounds = []

    def checks(self):
        rounds.append(self)
        if len(rounds) == 3:
            assert self is not rounds[1], 'post-repair findings must not accumulate old results'
            with pytest.raises(LibraryLockError), LibraryLock(str(db), kind='scan'):
                pass
            if check_fails:
                raise sqlite3.DatabaseError('post-repair read failed')
        return original(self)

    monkeypatch.setattr(DatabaseValidator, 'run_all_checks', checks)
    if check_fails:
        with pytest.raises(sqlite3.DatabaseError, match='post-repair read failed'):
            validate_db.main()
    else:
        assert validate_db.main() == 0
    assert len(rounds) == 3
    assert _blink(db) == 0
    with LibraryLock(str(db), kind='scan'):
        pass
