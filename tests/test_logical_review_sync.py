"""Review sync preserves source authority and exact viewer edit intent."""
import sqlite3

import pytest

from db import logical_assets as assets
from db import logical_asset_sync as groups
from db import logical_review as review
from db import logical_review_sync as sync

LABELS = {'/a.jpg': {'star_rating': 5, 'is_kept': 0, 'is_rejected': 0, 'is_favorite': 0},
          '/a.CR2': {'star_rating': 2, 'is_kept': 0, 'is_rejected': 0, 'is_favorite': 0}}


def write(conn, key, patch, owner='alice'):
    if not conn.in_transaction:
        conn.execute('BEGIN')
    revision = conn.execute('SELECT revision FROM logical_assets WHERE id=?', (key,)).fetchone()[0]
    state = review.read(conn, key, owner, LABELS)
    return review.set_fields(conn, key, owner, revision, state['revision'], patch, origin='user',
                             visibility_sql='1=1', file_labels=LABELS, input_token=state['input_token'])


@pytest.fixture
def pair(tmp_path):
    source = sqlite3.connect(tmp_path / 'source.db')
    source.execute('CREATE TABLE photos(path TEXT PRIMARY KEY)')
    assets.init_schema(source)
    review.init_schema(source)
    source.executemany('INSERT INTO photos VALUES (?)', [(path,) for path in LABELS])
    key = assets.create(source, list(LABELS), '/a.jpg', visibility_sql='1=1')
    review.seed(source, key, '/a.jpg', 1, visibility_sql='1=1')
    write(source, key, {'star_rating': 3})
    source.commit()
    viewer = sqlite3.connect(tmp_path / 'viewer.db')
    source.backup(viewer)
    groups.capture_imports(viewer)
    sync.capture_imports(viewer)
    viewer.commit()
    viewer.execute('ATTACH DATABASE ? AS src', (str(tmp_path / 'source.db'),))
    yield source, viewer, key
    viewer.close()
    source.close()


def merge(viewer):
    plan = groups.prepare_sync(viewer)
    imported = groups.sync_imports(viewer, plan)
    sync.sync_imports(viewer, imported, plan)
    viewer.commit()


def state(conn, key, owner='alice'):
    if not conn.in_transaction:
        conn.execute('BEGIN')
    return review.read(conn, key, owner, LABELS)


def test_repeated_imports_do_not_become_local_edits(pair):
    source, viewer, key = pair
    for rating in (4, 1, 2):
        write(source, key, {'star_rating': rating})
        source.commit()
        merge(viewer)
        assert state(viewer, key)['values']['star_rating'] == rating
        viewer.commit()


def test_same_value_local_edit_wins_but_other_source_fields_continue_syncing(pair):
    source, viewer, key = pair
    write(viewer, key, {'star_rating': 3})  # same value, explicit local ownership
    viewer.commit()
    write(source, key, {'star_rating': 4, 'is_favorite': 1})
    source.commit()
    merge(viewer)
    current = state(viewer, key)
    assert current['values']['star_rating'] == 3
    assert current['values']['is_favorite'] == 1
    viewer.commit()
    write(source, key, {'star_rating': 1, 'is_favorite': 0})
    source.commit()
    merge(viewer)
    current = state(viewer, key)
    assert current['values']['star_rating'] == 3 and current['values']['is_favorite'] == 0


def test_reset_is_preserved_across_repeated_source_exports(pair):
    source, viewer, key = pair
    current = state(viewer, key)
    review.reset_fields(viewer, key, 'alice', 1, current['revision'], ['star_rating'],
                        visibility_sql='1=1', file_labels=LABELS, input_token=current['input_token'])
    viewer.commit()
    for rating in (4, 2):
        write(source, key, {'star_rating': rating})
        source.commit()
        merge(viewer)
        current = state(viewer, key)
        assert current['values']['star_rating'] == 5 and current['origins']['star_rating'] == 'file'
        viewer.commit()


def test_source_reset_propagates_to_an_unchanged_import(pair):
    source, viewer, key = pair
    current = state(source, key)
    review.reset_fields(source, key, 'alice', 1, current['revision'], ['star_rating'],
                        visibility_sql='1=1', file_labels=LABELS, input_token=current['input_token'])
    source.commit()
    merge(viewer)
    assert state(viewer, key)['values']['star_rating'] == 5
    viewer.commit()
    write(source, key, {'star_rating': None})
    source.commit()
    merge(viewer)
    assert state(viewer, key)['values']['star_rating'] is None


def test_primary_changes_do_not_rebind_review_inheritance(pair):
    source, viewer, key = pair
    source.execute('BEGIN')
    assets.set_primary(source, key, '/a.CR2', 1, visibility_sql='1=1')
    source.commit()
    merge(viewer)
    assert state(viewer, key)['source_path'] == '/a.jpg'
    assert viewer.execute('SELECT primary_path FROM logical_assets WHERE id=?', (key,)).fetchone()[0] == '/a.CR2'


def test_locally_reviewed_group_is_not_destroyed_by_source_ungrouping(pair):
    source, viewer, key = pair
    write(viewer, key, {'star_rating': 4})
    viewer.commit()
    source.execute('BEGIN')
    assets.dissolve(source, key, 1, visibility_sql='1=1')
    source.commit()
    merge(viewer)
    assert state(viewer, key)['values']['star_rating'] == 4
    assert viewer.execute('SELECT COUNT(*) FROM logical_asset_members').fetchone()[0] == 2


def test_retired_review_is_local_history_not_active_photo_data(pair):
    source, viewer, key = pair
    viewer.execute('BEGIN')
    assets.dissolve(viewer, key, 1, visibility_sql='1=1')
    viewer.commit()
    merge(viewer)
    assert viewer.execute('SELECT value FROM logical_review_fields WHERE asset_id=?', (key,)).fetchone()[0] == 3
    with pytest.raises(assets.AssetConflict):
        state(viewer, key)
    sync.omit_retired(viewer)
    sync.capture_imports(viewer)
    assert viewer.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0
    assert viewer.execute('SELECT COUNT(*) FROM logical_review_imports').fetchone()[0] == 0


def test_import_failure_rolls_back_fields_clocks_and_receipts(pair):
    source, viewer, key = pair
    write(source, key, {'star_rating': 4})
    source.commit()
    before = viewer.execute('SELECT * FROM logical_review_imports').fetchall()
    viewer.execute("CREATE TRIGGER fail_review_update BEFORE UPDATE ON logical_review_fields "
                   "BEGIN SELECT RAISE(ABORT,'injected'); END")
    viewer.execute('BEGIN')
    plan = groups.prepare_sync(viewer)
    imported = groups.sync_imports(viewer, plan)
    with pytest.raises(sqlite3.IntegrityError):
        sync.sync_imports(viewer, imported, plan)
    assert state(viewer, key)['values']['star_rating'] == 3
    assert viewer.execute('SELECT * FROM logical_review_imports').fetchall() == before
    viewer.rollback()


def test_later_source_adoption_does_not_rebind_an_existing_viewer_seed(pair):
    source, viewer, key = pair
    # Model an older source adopting logical-review authority only after its
    # display primary had changed. The viewer's existing seed remains fixed.
    source.execute('UPDATE logical_review_seeds SET photo_path=? WHERE asset_id=?', ('/a.CR2', key))
    source.commit()
    merge(viewer)
    assert state(viewer, key)['source_path'] == '/a.jpg'


def test_source_relink_transfers_the_same_review_authority_to_new_member_path(pair):
    source, viewer, key = pair
    plan = groups.prepare_sync(viewer)
    viewer.commit()
    source.execute("UPDATE photos SET path='/moved/a.jpg' WHERE path='/a.jpg'")
    source.execute("DELETE FROM logical_review_fields WHERE field='star_rating'")
    source.commit()
    viewer.execute("DELETE FROM photos WHERE path='/a.jpg'")
    viewer.execute("INSERT INTO photos VALUES ('/moved/a.jpg')")
    imported = groups.sync_imports(viewer, plan)
    sync.sync_imports(viewer, imported, plan)
    labels = {'/moved/a.jpg': LABELS['/a.jpg'], '/a.CR2': LABELS['/a.CR2']}
    current = review.read(viewer, key, 'alice', labels)
    assert current['source_path'] == '/moved/a.jpg'
    assert current['values']['star_rating'] == 5


def test_source_regroup_cannot_erase_a_viewer_reset_of_the_last_field(pair):
    source, viewer, key = pair
    current = state(viewer, key)
    review.reset_fields(viewer, key, 'alice', 1, current['revision'], ['star_rating'],
                        visibility_sql='1=1', file_labels=LABELS, input_token=current['input_token'])
    viewer.commit()
    source.execute('BEGIN')
    assets.dissolve(source, key, 1, visibility_sql='1=1')
    replacement = assets.create(source, list(LABELS), '/a.CR2', visibility_sql='1=1')
    review.seed(source, replacement, '/a.CR2', 1, visibility_sql='1=1')
    source.commit()
    merge(viewer)
    assert viewer.execute('SELECT id FROM logical_assets').fetchall() == [(key,)]
    current = state(viewer, key)
    assert current['values']['star_rating'] == 5 and current['origins']['star_rating'] == 'file'
