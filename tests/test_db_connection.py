"""Tests for the sqlite-vec availability probe and loader in ``db.connection``.

The probe must answer "importable *and* loadable", not just "importable": a
pyenv / system Python whose bundled SQLite was built without extension loading
can still ``import sqlite_vec`` while every connection then raises
``AttributeError: 'sqlite3.Connection' object has no attribute
'enable_load_extension'``. Treating that as available made the viewer log a
traceback on every async request instead of using the NumPy search fallback.
"""

import sqlite3
import sys
from unittest import mock

import pytest

import db.connection as conn


# ``conn.sqlite3`` IS the stdlib module, so patching ``connect`` through it is
# process-wide for the duration of the ``with``. There is no module-local alias
# to aim at instead, and pytest runs these bodies single-threaded, so nothing
# else is reading ``sqlite3.connect`` while the patch is in place.
_patch_connect = "db.connection.sqlite3.connect"


def test_probe_false_when_import_fails():
    """A missing sqlite_vec package is reported False, never raised.

    A ``None`` entry in ``sys.modules`` makes the ``import`` statement raise
    ImportError, exactly as if the package were not installed.
    """
    with mock.patch.dict(sys.modules, {"sqlite_vec": None}):
        assert conn._probe_sqlite_vec() is False


def test_probe_false_when_extension_loading_unavailable():
    """Importable sqlite_vec + a sqlite3 that cannot load extensions -> False.

    Reproduces the macOS pyenv build: the import succeeds but the connection
    object has no ``enable_load_extension``. The throwaway probe connection is
    still closed via the finally block.
    """
    fake_sqlite_vec = mock.MagicMock()
    fake_conn = mock.MagicMock()
    del fake_conn.enable_load_extension  # accessing it now raises AttributeError

    with mock.patch.dict(sys.modules, {"sqlite_vec": fake_sqlite_vec}), \
            mock.patch(_patch_connect, return_value=fake_conn):
        assert conn._probe_sqlite_vec() is False

    fake_conn.close.assert_called_once()


def test_probe_true_when_extension_loads():
    """An importable package whose extension loads on a probe connection -> True."""
    fake_sqlite_vec = mock.MagicMock()
    fake_conn = mock.MagicMock()

    with mock.patch.dict(sys.modules, {"sqlite_vec": fake_sqlite_vec}), \
            mock.patch(_patch_connect, return_value=fake_conn):
        assert conn._probe_sqlite_vec() is True

    fake_conn.enable_load_extension.assert_called_once_with(True)
    fake_sqlite_vec.load.assert_called_once_with(fake_conn)
    fake_conn.close.assert_called_once()


@pytest.mark.skipif(
    not conn.HAS_SQLITE_VEC, reason="sqlite_vec is not loadable in this sqlite3"
)
def test_load_sqlite_vec_makes_vec0_usable_on_a_healthy_build():
    """The synchronous loader still works now that ``sqlite_vec`` is function-local.

    The probe no longer binds ``sqlite_vec`` at module scope, so
    ``load_sqlite_vec`` carries its own import. Without it the name is unbound
    and every synchronous vec load breaks -- silently, because the loader
    swallows the failure at ``debug`` level, which is exactly why the assertion
    here is on a working ``vec0`` rather than on the call returning.
    """
    c = sqlite3.connect(":memory:")
    try:
        conn.load_sqlite_vec(c)
        c.execute(
            "CREATE VIRTUAL TABLE t USING vec0(id INTEGER PRIMARY KEY, embedding float[4])"
        )
        c.execute("INSERT INTO t (id, embedding) VALUES (1, ?)", [b"\x00" * 16])
        assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    finally:
        c.close()


@pytest.mark.parametrize("filename", [
    "library #%-相册.db",
    pytest.param("library?.db", marks=pytest.mark.skipif(
        sys.platform == "win32", reason="Windows filenames cannot contain a question mark")),
])
def test_read_only_connection_preserves_literal_path_and_rejects_writes(tmp_path, filename):
    path = tmp_path / filename
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE marker (value TEXT)')
        db.execute("INSERT INTO marker VALUES ('original')")
    before = path.read_bytes()
    with conn.get_connection(path, read_only=True) as db:
        assert db.execute('SELECT value FROM marker').fetchone()['value'] == 'original'
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute("UPDATE marker SET value='changed'")
    assert path.read_bytes() == before
    assert {p.name for p in tmp_path.iterdir()} == {path.name}


def test_read_only_connection_never_creates_a_missing_database(tmp_path):
    path = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.OperationalError):
        with conn.get_connection(path, read_only=True):
            pass
    assert not path.exists()
