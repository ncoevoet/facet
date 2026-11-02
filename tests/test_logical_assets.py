"""Durable logical identity uses disposable catalogs, not the user's library."""
import sqlite3

import pytest

from db import logical_assets as assets


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / 'catalog.db'
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY, rating INTEGER)')
    assets.init_schema(conn)
    conn.executemany('INSERT INTO photos VALUES (?,?)', [('/a.jpg', 5), ('/a.CR2', 2), ('/a.NEF', 3)])
    conn.commit()
    yield conn, path
    conn.close()


def group(conn, paths=('/a.jpg', '/a.CR2'), primary='/a.jpg'):
    return assets.create(conn, list(paths), primary, visibility_sql='1=1')


def test_explicit_primary_survives_restart_and_preserves_conflicting_metadata(catalog):
    conn, path = catalog
    conn.execute('BEGIN IMMEDIATE')
    asset_id = group(conn)
    assert assets.set_primary(conn, asset_id, '/a.CR2', 1, visibility_sql='1=1') == 2
    conn.commit()
    with sqlite3.connect(path) as other:
        assert other.execute('SELECT id,primary_path,revision FROM logical_assets').fetchall() == [(asset_id, '/a.CR2', 2)]
        assert other.execute('SELECT path,rating FROM photos ORDER BY path').fetchall() == [('/a.CR2', 2), ('/a.NEF', 3), ('/a.jpg', 5)]
        assert other.execute('SELECT COUNT(*) FROM logical_asset_members').fetchone()[0] == 2


def test_stale_primary_and_hidden_member_refusals_leave_state_unchanged(catalog):
    conn, _ = catalog
    conn.execute('BEGIN')
    asset_id = group(conn)
    assets.set_primary(conn, asset_id, '/a.CR2', 1, visibility_sql='1=1')
    before = conn.execute('SELECT * FROM logical_assets').fetchall()
    with pytest.raises(assets.AssetConflict):
        assets.set_primary(conn, asset_id, '/a.jpg', 1, visibility_sql='1=1')
    with pytest.raises(assets.AssetConflict):
        assets.dissolve(conn, asset_id, 2, visibility_sql='path != ?', visibility_params=['/a.CR2'])
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == before
    conn.rollback()
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == []


def test_overlap_and_unauthorized_create_do_not_partially_mutate(catalog):
    conn, _ = catalog
    conn.execute('BEGIN')
    with pytest.raises(assets.AssetConflict):
        assets.create(conn, ['/a.jpg', '/a.CR2'], '/a.jpg', visibility_sql='path != ?', visibility_params=['/a.CR2'])
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == []
    group(conn)
    with pytest.raises(assets.AssetConflict):
        group(conn, ('/a.jpg', '/a.NEF'))
    assert conn.execute('SELECT COUNT(*) FROM logical_assets').fetchone()[0] == 1
    assert conn.execute('SELECT COUNT(*) FROM logical_asset_members').fetchone()[0] == 2


def test_caller_rollback_and_dissolve_preserve_photos(catalog):
    conn, _ = catalog
    conn.execute('BEGIN')
    asset_id = group(conn)
    assets.dissolve(conn, asset_id, 1, visibility_sql='1=1')
    assert conn.execute('SELECT * FROM logical_asset_members').fetchall() == []
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 3
    conn.rollback()
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == []


def test_rescan_replace_preserves_membership_and_explicit_move_updates_primary(catalog):
    conn, _ = catalog
    conn.execute('BEGIN')
    asset_id = group(conn)
    conn.execute("INSERT OR REPLACE INTO photos VALUES ('/a.jpg',4)")
    assert conn.execute('SELECT * FROM logical_assets').fetchone() == (asset_id, '/a.jpg', 1)
    assert conn.execute('SELECT COUNT(*) FROM logical_asset_members').fetchone()[0] == 2
    conn.execute("UPDATE photos SET path='/renamed.jpg' WHERE path='/a.jpg'")
    assert conn.execute('SELECT * FROM logical_assets').fetchone() == (asset_id, '/renamed.jpg', 2)
    assert conn.execute('SELECT photo_path FROM logical_asset_members ORDER BY position').fetchall() == [('/renamed.jpg',), ('/a.CR2',)]


def test_removed_primary_requires_new_choice_and_last_pair_dissolves(catalog):
    conn, _ = catalog
    conn.execute('BEGIN')
    asset_id = group(conn, ('/a.jpg', '/a.CR2', '/a.NEF'))
    conn.execute("DELETE FROM photos WHERE path='/a.jpg'")
    assert conn.execute('SELECT * FROM logical_assets').fetchone() == (asset_id, None, 2)
    assets.set_primary(conn, asset_id, '/a.NEF', 2, visibility_sql='1=1')
    conn.execute("DELETE FROM photos WHERE path='/a.CR2'")
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == []
    assert conn.execute('SELECT * FROM logical_asset_members').fetchall() == []
    assert conn.execute('SELECT * FROM photos').fetchall() == [('/a.NEF', 3)]


def test_requires_transaction_and_valid_raw_jpeg_members(catalog):
    conn, _ = catalog
    with pytest.raises(assets.AssetConflict):
        group(conn)
    conn.execute('BEGIN')
    for paths, primary in [(['/a.jpg', '/a.jpg'], '/a.jpg'), (['/a.CR2', '/a.NEF'], '/a.CR2'),
                           (['/a.jpg', '/a.CR2'], '/not-a-member.jpg')]:
        with pytest.raises(assets.AssetConflict):
            group(conn, paths, primary)
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == []


def test_mid_write_failure_rolls_back_only_asset_mutation(catalog):
    conn, _ = catalog
    conn.execute("CREATE TRIGGER fail_second_asset_member BEFORE INSERT ON logical_asset_members "
                 "WHEN NEW.position=1 BEGIN SELECT RAISE(ABORT,'injected storage failure'); END")
    conn.execute('BEGIN')
    conn.execute("UPDATE photos SET rating=4 WHERE path='/a.jpg'")
    with pytest.raises(sqlite3.IntegrityError, match='injected storage failure'):
        group(conn)
    assert conn.in_transaction
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == []
    assert conn.execute('SELECT * FROM logical_asset_members').fetchall() == []
    assert conn.execute("SELECT rating FROM photos WHERE path='/a.jpg'").fetchone()[0] == 4
    conn.rollback()
    assert conn.execute("SELECT rating FROM photos WHERE path='/a.jpg'").fetchone()[0] == 5


def test_explicit_delete_cleanup_does_not_require_foreign_keys(catalog):
    conn, _ = catalog
    conn.execute('PRAGMA foreign_keys=OFF')
    conn.execute('BEGIN')
    asset_id = group(conn)
    assets.dissolve(conn, asset_id, 1, visibility_sql='1=1')
    assert conn.execute('SELECT * FROM logical_asset_members').fetchall() == []
    group(conn)
    conn.execute("DELETE FROM photos WHERE path='/a.CR2'")
    assert conn.execute('SELECT * FROM logical_assets').fetchall() == []
    assert conn.execute('SELECT * FROM logical_asset_members').fetchall() == []


def test_boolean_revision_cannot_authorize_a_primary_change(catalog):
    conn, _ = catalog
    conn.execute('BEGIN')
    asset_id = group(conn)
    with pytest.raises(assets.AssetConflict):
        assets.set_primary(conn, asset_id, '/a.CR2', True, visibility_sql='1=1')
    assert conn.execute('SELECT primary_path,revision FROM logical_assets').fetchone() == ('/a.jpg', 1)


def test_real_scanner_upsert_preserves_membership_with_recursive_triggers(catalog):
    from processing.scorer import _photos_upsert

    conn, _ = catalog
    conn.execute('PRAGMA recursive_triggers=ON')
    conn.execute('BEGIN')
    asset_id = group(conn)
    sql = _photos_upsert('INSERT OR REPLACE INTO photos(path,rating) VALUES (?,?)')
    conn.execute(sql, ('/a.jpg', 4))
    assert conn.execute('SELECT * FROM logical_assets').fetchone() == (asset_id, '/a.jpg', 1)
    assert conn.execute('SELECT COUNT(*) FROM logical_asset_members').fetchone()[0] == 2


def test_rename_collision_rolls_back_without_retargeting_membership(catalog):
    conn, _ = catalog
    conn.execute('BEGIN')
    asset_id = group(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE photos SET path='/a.CR2' WHERE path='/a.jpg'")
    assert conn.execute('SELECT * FROM logical_assets').fetchone() == (asset_id, '/a.jpg', 1)
    assert conn.execute('SELECT photo_path FROM logical_asset_members ORDER BY position').fetchall() == [('/a.jpg',), ('/a.CR2',)]
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 3
