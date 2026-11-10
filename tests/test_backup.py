"""Tests for backup_database / check_disk_space (db/maintenance.py)."""

import glob
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Barrier
from unittest import mock

import pytest

from db.maintenance import backup_database, check_disk_space, export_viewer_db
from db.schema import init_database


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()


class TestBackupDatabase:
    @pytest.mark.parametrize("filename,other_name", [("library?.db", "libraryA.db"), ("library[1].db", "library1.db")])
    def test_rotation_matches_literal_path_and_preserves_other_libraries(self, tmp_path, filename, other_name):
        if os.name == "nt" and "?" in filename:
            pytest.skip("Windows filenames cannot contain a question mark")
        directory = tmp_path / "backups[1]"
        directory.mkdir()
        db = directory / filename
        _make_db(str(db), 2)
        own_old = directory / f"{filename}.backup-20000101-000000"
        other = directory / f"{other_name}.backup-20000101-000000"
        own_old.write_bytes(b"older own snapshot")
        other.write_bytes(b"unrelated snapshot")
        os.utime(own_old, (1, 1))
        os.utime(other, (1, 1))
        backup = backup_database(str(db), keep=1, verbose=False)
        assert not own_old.exists()
        assert other.read_bytes() == b"unrelated snapshot"
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2

    @pytest.mark.parametrize("filename", ["library#one.db", "library?mode=rw.db", "library%23one.db", "相册 space.db"])
    def test_backup_uses_the_literal_source_path(self, tmp_path, filename):
        from db.schema import init_database

        if os.name == "nt" and "?" in filename:
            pytest.skip("Windows filenames cannot contain a question mark")
        db = tmp_path / filename
        init_database(str(db))
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO photos (path) VALUES (?)", ("/literal-source.jpg",))
        # The decoded/truncated sibling must never be mistaken for the source.
        decoy = tmp_path / filename.replace("%23", "#").split("?", 1)[0].split("#", 1)[0]
        if decoy != db:
            init_database(str(decoy))
        before = db.read_bytes()
        backup = backup_database(str(db), verbose=False)
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT path FROM photos").fetchall() == [("/literal-source.jpg",)]
        assert db.read_bytes() == before

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
        if os.name == 'nt' and any(char in name for char in '*?'):
            pytest.skip('Windows filenames cannot contain * or ?')
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


@contextmanager
def _committing_writer(path):
    """Commit to ``path`` from another connection, as a scan or the viewer would."""
    stop = threading.Event()
    commits = []

    def write():
        with closing(sqlite3.connect(path, timeout=5)) as conn:
            while not stop.is_set():
                conn.execute('UPDATE live SET n = n + 1')
                conn.commit()
                commits.append(time.monotonic())
                time.sleep(0.005)

    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    try:
        yield commits
    finally:
        stop.set()
        writer.join(10)


@pytest.mark.parametrize('operation', ['backup', 'export'])
def test_live_library_copy_finishes_while_another_connection_commits(tmp_path, operation):
    db = tmp_path / 'library.db'
    init_database(str(db), build_photo_indexes=False)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE live(n INTEGER)')
        conn.execute('INSERT INTO live VALUES(0)')
        conn.execute('CREATE TABLE bulk(blob BLOB)')
        # Enough pages that a copy in 256-page steps spans many writer commits.
        conn.executemany('INSERT INTO bulk VALUES(randomblob(8192))', [()] * 6144)
    copy = {
        'backup': lambda: backup_database(str(db), keep=3, verbose=False),
        'export': lambda: export_viewer_db(str(db), str(tmp_path / 'viewer.db'), verbose=False),
    }[operation]
    # The writer stops first on exit, so a copy that never finishes fails the
    # timeout below instead of hanging the executor's shutdown.
    with ThreadPoolExecutor(max_workers=1) as executor, _committing_writer(db) as commits:
        deadline = time.monotonic() + 10
        while not commits and time.monotonic() < deadline:
            time.sleep(0.01)
        assert commits, 'the writer must be committing before the copy starts'
        executor.submit(copy).result(timeout=10)
