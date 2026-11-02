"""Upgrade an actual previous trigger policy without guessing a new primary."""
from contextlib import closing
import sqlite3

from db import logical_assets as assets
from db.schema import init_database, SCHEMA_VERSION


def test_previous_pair_cleanup_is_upgraded_and_idempotent(tmp_path):
    path = str(tmp_path / 'catalog.db')
    init_database(path, build_photo_indexes=False)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executemany('INSERT INTO photos(path,filename) VALUES (?,?)', [('/a.jpg', 'a.jpg'), ('/a.CR2', 'a.CR2')])
        key = assets.create(conn, ['/a.jpg', '/a.CR2'], '/a.jpg', visibility_sql='1=1')
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='logical_asset_member_delete'").fetchone()[0]
        assert '<1' in sql
        conn.execute('DROP TRIGGER logical_asset_member_delete')
        conn.execute(sql.replace('<1', '<2'))  # exact prior policy, same complete trigger
        conn.execute('PRAGMA user_version=1')
    old = sqlite3.connect(tmp_path / 'old-policy.db')
    with closing(sqlite3.connect(path)) as source:
        source.backup(old)
    old.execute("DELETE FROM photos WHERE path='/a.jpg'")
    assert old.execute('SELECT * FROM logical_assets').fetchall() == []
    old.close()

    init_database(path, build_photo_indexes=False)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION == 2
        assert conn.execute('SELECT id,primary_path,revision FROM logical_assets').fetchall() == [(key, '/a.jpg', 1)]
        conn.execute("DELETE FROM photos WHERE path='/a.jpg'")
        assert conn.execute('SELECT id,primary_path,revision FROM logical_assets').fetchall() == [(key, None, 2)]
        assert conn.execute('SELECT photo_path FROM logical_asset_members').fetchall() == [('/a.CR2',)]
    init_database(path, build_photo_indexes=False)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT id,primary_path,revision FROM logical_assets').fetchall() == [(key, None, 2)]
