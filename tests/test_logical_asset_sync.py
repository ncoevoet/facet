"""Catalog relationship sync distinguishes imported receipts from viewer edits."""
import sqlite3

import pytest

from db import logical_assets as assets
from db import logical_asset_sync as sync


def catalog(path):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY, rating INTEGER)')
    assets.init_schema(conn)
    conn.executemany('INSERT INTO photos VALUES (?,0)', [(path,) for path in ['/a.jpg', '/a.CR2', '/a.NEF', '/b.jpg', '/b.CR2']])
    conn.commit()
    return conn


@pytest.fixture
def pair(tmp_path):
    source = catalog(tmp_path / 'source.db')
    source.execute('BEGIN')
    key = assets.create(source, ['/a.jpg', '/a.CR2', '/a.NEF'], '/a.jpg', visibility_sql='1=1')
    source.commit()
    viewer = sqlite3.connect(tmp_path / 'viewer.db')
    source.backup(viewer)
    sync.capture_imports(viewer)
    viewer.commit()
    viewer.execute('ATTACH DATABASE ? AS src', (str(tmp_path / 'source.db'),))
    yield source, viewer, key
    viewer.close()
    source.close()


def primary(conn, key):
    return conn.execute('SELECT primary_path,revision FROM logical_assets WHERE id=?', (key,)).fetchone()


def change(conn, key, value, revision):
    conn.execute('BEGIN')
    assets.set_primary(conn, key, value, revision, visibility_sql='1=1')
    conn.commit()


def test_repeated_sync_tracks_source_without_turning_receipts_into_viewer_edits(pair):
    source, viewer, key = pair
    change(source, key, '/a.CR2', 1)
    sync.sync_imports(viewer)
    viewer.commit()
    assert primary(viewer, key) == ('/a.CR2', 2)
    change(source, key, '/a.NEF', 2)
    sync.sync_imports(viewer)
    viewer.commit()
    assert primary(viewer, key) == ('/a.NEF', 3)
    sync.sync_imports(viewer)
    assert primary(viewer, key) == ('/a.NEF', 3)


def test_viewer_primary_and_dissolution_survive_source_updates(pair):
    source, viewer, key = pair
    change(viewer, key, '/a.CR2', 1)
    change(source, key, '/a.NEF', 1)
    sync.sync_imports(viewer)
    viewer.commit()
    assert primary(viewer, key) == ('/a.CR2', 2)
    viewer.execute('BEGIN')
    assets.dissolve(viewer, key, 2, visibility_sql='1=1')
    viewer.commit()
    sync.sync_imports(viewer)
    viewer.commit()
    assert primary(viewer, key) is None
    sync.sync_imports(viewer)
    assert primary(viewer, key) is None


def test_source_deletion_removes_unchanged_import_but_preserves_local_group(pair):
    source, viewer, key = pair
    source.execute('BEGIN')
    assets.dissolve(source, key, 1, visibility_sql='1=1')
    source.commit()
    sync.sync_imports(viewer)
    assert primary(viewer, key) is None
    assert viewer.execute('SELECT COUNT(*) FROM logical_asset_members').fetchone()[0] == 0


def test_photo_sync_cleanup_is_not_mistaken_for_viewer_intent(pair):
    source, viewer, key = pair
    preserved = sync.prepare_sync(viewer)
    viewer.commit()
    source.execute("DELETE FROM photos WHERE path='/a.jpg'")
    source.commit()
    change(source, key, '/a.NEF', 2)
    viewer.execute("DELETE FROM photos WHERE path='/a.jpg'")
    sync.sync_imports(viewer, preserved)
    viewer.commit()
    assert primary(viewer, key) == ('/a.NEF', 3)


def test_new_source_group_cannot_take_member_from_a_viewer_owned_group(pair):
    source, viewer, key = pair
    viewer.execute('BEGIN')
    assets.dissolve(viewer, key, 1, visibility_sql='1=1')
    local = assets.create(viewer, ['/a.jpg', '/b.CR2'], '/a.jpg', visibility_sql='1=1')
    viewer.commit()
    sync.sync_imports(viewer)
    assert primary(viewer, local) == ('/a.jpg', 1)
    assert primary(viewer, key) is None


def test_sync_failure_does_not_leave_a_partial_import(pair):
    source, viewer, key = pair
    change(source, key, '/a.CR2', 1)
    viewer.execute("CREATE TRIGGER fail_import BEFORE INSERT ON logical_asset_members "
                   "WHEN NEW.position=1 BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = primary(viewer, key)
    with pytest.raises(sqlite3.IntegrityError):
        sync.sync_imports(viewer)
    assert primary(viewer, key) == before
    assert viewer.execute('SELECT COUNT(*) FROM logical_asset_members').fetchone()[0] == 3


def test_sync_keeps_commit_owned_by_the_caller(pair):
    source, viewer, key = pair
    change(source, key, '/a.CR2', 1)
    assert not viewer.in_transaction
    sync.sync_imports(viewer)
    assert viewer.in_transaction
    assert primary(viewer, key) == ('/a.CR2', 2)
    viewer.rollback()
    assert primary(viewer, key) == ('/a.jpg', 1)


def test_new_source_group_id_does_not_resurrect_viewer_ungrouped_files(pair):
    source, viewer, key = pair
    viewer.execute('BEGIN')
    assets.dissolve(viewer, key, 1, visibility_sql='1=1')
    viewer.commit()
    source.execute('BEGIN')
    assets.dissolve(source, key, 1, visibility_sql='1=1')
    replacement = assets.create(source, ['/a.jpg', '/a.CR2'], '/a.CR2', visibility_sql='1=1')
    source.commit()
    sync.sync_imports(viewer)
    assert primary(viewer, replacement) is None
    assert viewer.execute('SELECT * FROM logical_assets').fetchall() == []


def test_viewer_primary_changed_during_photo_sync_is_preserved(pair):
    source, viewer, key = pair
    prepared = sync.prepare_sync(viewer)
    viewer.commit()
    change(viewer, key, '/a.CR2', 1)
    change(source, key, '/a.NEF', 1)
    sync.sync_imports(viewer, prepared)
    assert primary(viewer, key) == ('/a.CR2', 2)


def test_source_changes_between_snapshot_queries_cannot_mix_revisions(pair):
    source, viewer, key = pair
    source.execute('PRAGMA journal_mode=WAL')
    fired = False

    def update_between_reads(sql):
        nonlocal fired
        if 'SELECT id,primary_path,revision FROM src.logical_assets' in sql and not fired:
            fired = True
            change(source, key, '/a.CR2', 1)

    viewer.set_trace_callback(update_between_reads)
    try:
        sync.sync_imports(viewer)
        viewer.commit()
    finally:
        viewer.set_trace_callback(None)
    assert fired
    assert primary(source, key) == ('/a.CR2', 2)
    assert primary(viewer, key) == ('/a.jpg', 1)
    sync.sync_imports(viewer)
    assert primary(viewer, key) == ('/a.CR2', 2)
