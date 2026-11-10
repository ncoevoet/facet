"""Repair is a library job, including the interactive path."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from db.schema import init_database
from facet import LibraryLock


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
    assert result.returncode == 0, result.stdout + result.stderr
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
    validate_db.main()
    assert _blink(db) == 0
    with LibraryLock(str(db), kind='scan'):
        pass
