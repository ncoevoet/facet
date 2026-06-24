"""Tests for backup_database / check_disk_space (db/maintenance.py)."""

import glob
import os
import sqlite3
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

    def test_refuses_when_insufficient_space(self, tmp_path):
        db = tmp_path / "photo_scores_pro.db"
        _make_db(str(db), 3)

        fake_usage = mock.Mock()
        fake_usage.free = 0
        with mock.patch("db.maintenance.shutil.disk_usage", return_value=fake_usage):
            with pytest.raises(RuntimeError, match="free space"):
                backup_database(str(db), verbose=False)


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
