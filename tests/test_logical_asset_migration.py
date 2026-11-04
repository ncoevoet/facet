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


def test_pre_review_groups_adopt_once_without_following_later_primary_changes(tmp_path):
    path = str(tmp_path / 'before-review.db')
    # Pre-review table definitions from c952e447, before review authority existed.
    # Start with those tables, rather than deleting new tables from a current DB.
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript("""
            CREATE TABLE photos(path TEXT PRIMARY KEY, filename TEXT);
            CREATE TABLE logical_assets(id TEXT PRIMARY KEY, primary_path TEXT,
                revision INTEGER NOT NULL CHECK(revision > 0));
            CREATE TABLE logical_asset_members(
                asset_id TEXT NOT NULL REFERENCES logical_assets(id) ON DELETE CASCADE,
                photo_path TEXT NOT NULL UNIQUE, position INTEGER NOT NULL CHECK(position >= 0),
                PRIMARY KEY(asset_id,photo_path), UNIQUE(asset_id,position));
            INSERT INTO photos VALUES('/a.jpg','a.jpg'),('/a.CR2','a.CR2');
            INSERT INTO logical_assets VALUES('pair','/a.jpg',1);
            INSERT INTO logical_asset_members VALUES('pair','/a.jpg',0),('pair','/a.CR2',1);
            PRAGMA user_version=1;
        """)
    init_database(path, build_photo_indexes=False)
    with closing(sqlite3.connect(path)) as conn, conn:
        assert conn.execute('SELECT * FROM logical_review_seeds').fetchall() == [('pair', '/a.jpg')]
        conn.execute("UPDATE logical_assets SET primary_path='/a.CR2', revision=2 WHERE id='pair'")
    init_database(path, build_photo_indexes=False)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT * FROM logical_review_seeds').fetchall() == [('pair', '/a.jpg')]
        assert conn.execute('SELECT primary_path,revision FROM logical_assets').fetchall() == [('/a.CR2', 2)]
