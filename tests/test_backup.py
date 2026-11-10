"""Tests for backup_database / check_disk_space (db/maintenance.py)."""

import glob
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import mock

import pytest

from db.maintenance import backup_database, check_disk_space


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


class TestBackupDatabase:
    def test_backup_is_a_faithful_copy(self, tmp_path):
        db = tmp_path / "photo_scores_pro.db"
        _make_db(str(db), 7)

        backup_path = backup_database(str(db), keep=3, verbose=False)

        assert os.path.exists(backup_path)
        assert backup_path.startswith(str(db) + ".backup-")
        # Backup opens and has the same row count
        conn = sqlite3.connect(backup_path)
        count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        conn.close()
        assert count == 7

    def test_original_untouched(self, tmp_path):
        db = tmp_path / "photo_scores_pro.db"
        _make_db(str(db), 5)
        before = db.read_bytes()

        backup_database(str(db), keep=3, verbose=False)

        assert db.read_bytes() == before

    def test_rotation_keeps_only_newest(self, tmp_path):
        db = tmp_path / "photo_scores_pro.db"
        _make_db(str(db), 3)

        # Two snapshots with keep=1 — only the newest survives. Distinct
        # timestamps are forced via the datetime used inside backup_database.
        with mock.patch("db.maintenance.datetime") as dt:
            dt.now.return_value.strftime.return_value = "20260101-000001"
            backup_database(str(db), keep=1, verbose=False)
        with mock.patch("db.maintenance.datetime") as dt:
            dt.now.return_value.strftime.return_value = "20260101-000002"
            kept = backup_database(str(db), keep=1, verbose=False)

        backups = glob.glob(str(db) + ".backup-*")
        assert backups == [kept]

    def test_missing_db_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            backup_database(str(tmp_path / "nope.db"), verbose=False)

    def test_keep_below_one_is_rejected_and_leaves_no_backup(self, tmp_path):
        db = tmp_path / "photo_scores_pro.db"
        _make_db(str(db), 4)

        with pytest.raises(ValueError, match="keep must be at least"):
            backup_database(str(db), keep=0, verbose=False)

        assert glob.glob(str(db) + ".backup-*") == []
        assert os.path.exists(db)

    def test_refuses_when_insufficient_space(self, tmp_path):
        db = tmp_path / "photo_scores_pro.db"
        _make_db(str(db), 3)

        fake_usage = mock.Mock()
        fake_usage.free = 0
        with mock.patch("db.maintenance.shutil.disk_usage", return_value=fake_usage):
            with pytest.raises(RuntimeError, match="free space"):
                backup_database(str(db), verbose=False)

    def test_same_second_snapshots_are_distinct_and_faithful(self, tmp_path):
        db = tmp_path / 'library.db'
        _make_db(db, 3)
        with mock.patch('db.maintenance.datetime') as dt:
            dt.now.return_value.strftime.return_value = '20260101-000001'
            first = backup_database(str(db), keep=3, verbose=False)
            before = Path(first).read_bytes()
            with sqlite3.connect(db) as conn:
                conn.execute("INSERT INTO t(v) VALUES('later')")
            second = backup_database(str(db), keep=3, verbose=False)
        assert first != second
        assert Path(first).read_bytes() == before
        with sqlite3.connect(second) as conn:
            assert conn.execute('SELECT COUNT(*) FROM t').fetchone() == (4,)

    def test_failed_same_second_copy_does_not_destroy_prior_backup(self, tmp_path, monkeypatch):
        db = tmp_path / 'library.db'
        _make_db(db, 3)
        with mock.patch('db.maintenance.datetime') as dt:
            dt.now.return_value.strftime.return_value = '20260101-000001'
            previous = backup_database(str(db), keep=3, verbose=False)
            before = Path(previous).read_bytes()
            connect = sqlite3.connect

            class FailingCopy(sqlite3.Connection):
                def backup(self, target, **kwargs):
                    raise KeyboardInterrupt('cancelled copy')

            monkeypatch.setattr('db.maintenance.sqlite3.connect',
                                lambda *a, **kw: connect(*a, **(kw | {'factory': FailingCopy})))
            with pytest.raises(KeyboardInterrupt, match='cancelled copy'):
                backup_database(str(db), keep=3, verbose=False)
        assert Path(previous).read_bytes() == before
        assert set(tmp_path.iterdir()) == {db, Path(previous)}

    def test_concurrent_same_second_backups_never_share_an_in_progress_file(self, tmp_path, monkeypatch):
        db = tmp_path / 'library.db'
        _make_db(db, 3)
        start = Barrier(2)
        connect = sqlite3.connect

        class ConcurrentCopy(sqlite3.Connection):
            def backup(self, target, **kwargs):
                start.wait(timeout=5)
                return super().backup(target, **kwargs)

        monkeypatch.setattr('db.maintenance.sqlite3.connect',
                            lambda *a, **kw: connect(*a, **(kw | {'factory': ConcurrentCopy})))
        with mock.patch('db.maintenance.datetime') as dt, ThreadPoolExecutor(max_workers=2) as executor:
            dt.now.return_value.strftime.return_value = '20260101-000001'
            jobs = [executor.submit(backup_database, str(db), keep=3, verbose=False) for _ in range(2)]
            paths = [job.result(timeout=10) for job in jobs]
        assert len(set(paths)) == 2
        for path in paths:
            with connect(path) as conn:
                assert conn.execute('SELECT COUNT(*) FROM t').fetchone() == (3,)
                assert conn.execute('PRAGMA integrity_check').fetchone() == ('ok',)

    @pytest.mark.parametrize(('name', 'other'), [('library[1].db', 'library1.db'),
                                               ('library*.db', 'library2.db'),
                                               ('library?.db', 'library3.db')])
    def test_rotation_uses_literal_database_names(self, tmp_path, name, other):
        from db.maintenance import _rotate_backups
        own = tmp_path / (name + '.backup-old')
        latest = tmp_path / (name + '.backup-new')
        unrelated = tmp_path / (other + '.backup-old')
        for path in (unrelated, own, latest):
            path.write_bytes(b'completed snapshot')
        os.utime(unrelated, (1, 1))
        os.utime(own, (2, 2))
        os.utime(latest, (3, 3))
        _rotate_backups(str(tmp_path / name), str(tmp_path), 1)
        assert not own.exists()
        assert latest.exists()
        assert unrelated.read_bytes() == b'completed snapshot'

    def test_rotation_uses_literal_parent_directory(self, tmp_path):
        from db.maintenance import _rotate_backups
        own_dir, other_dir = tmp_path / 'library[1]', tmp_path / 'library1'
        own_dir.mkdir()
        other_dir.mkdir()
        own = own_dir / 'photos.db.backup-old'
        latest = own_dir / 'photos.db.backup-new'
        unrelated = other_dir / 'photos.db.backup-old'
        for path in (unrelated, own, latest):
            path.write_bytes(b'completed snapshot')
        os.utime(unrelated, (1, 1))
        os.utime(own, (2, 2))
        os.utime(latest, (3, 3))
        _rotate_backups(str(own_dir / 'photos.db'), str(own_dir), 1)
        assert not own.exists()
        assert latest.exists()
        assert unrelated.read_bytes() == b'completed snapshot'


class TestCheckDiskSpace:
    def test_ok_when_enough(self, tmp_path):
        ok, free, required = check_disk_space(str(tmp_path), 10)
        assert ok is True
        assert required == 12  # 10 * 1.2

    def test_not_ok_when_low(self, tmp_path):
        fake_usage = mock.Mock()
        fake_usage.free = 5
        with mock.patch("db.maintenance.shutil.disk_usage", return_value=fake_usage):
            ok, free, required = check_disk_space(str(tmp_path), 100)
        assert ok is False
        assert free == 5
