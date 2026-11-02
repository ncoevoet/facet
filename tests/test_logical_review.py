"""Separate logical review identity never rewrites original file decisions."""
import sqlite3

import pytest

from db import logical_assets as assets
from db import logical_review as review

LABELS = {
    '/a.jpg': {'star_rating': 5, 'is_kept': 1, 'is_rejected': 0, 'is_favorite': 0},
    '/a.CR2': {'star_rating': 2, 'is_kept': 0, 'is_rejected': 1, 'is_favorite': 0},
}


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / 'catalog.db'
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY, star_rating INTEGER)')
    assets.init_schema(conn)
    review.init_schema(conn)
    conn.executemany('INSERT INTO photos VALUES (?,?)', [('/a.jpg', 5), ('/a.CR2', 2)])
    conn.commit()
    conn.execute('BEGIN')
    key = assets.create(conn, list(LABELS), '/a.jpg', visibility_sql='1=1')
    review.seed(conn, key, '/a.jpg', 1, visibility_sql='1=1')
    conn.commit()
    yield conn, path, key
    conn.close()


def write(conn, key, patch, owner='alice', version=0, group=1, origin='user', **policy):
    return review.set_fields(conn, key, owner, group, version, patch, origin=origin,
                             visibility_sql=policy.get('visibility_sql', '1=1'),
                             visibility_params=policy.get('visibility_params', ()), file_labels=LABELS,
                             input_token=review.read(conn, key, owner, LABELS)['input_token'])


def test_display_primary_changes_do_not_change_inherited_or_edited_review(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    assets.set_primary(conn, key, '/a.CR2', 1, visibility_sql='1=1')
    assert review.read(conn, key, 'alice', LABELS)['values']['star_rating'] == 5
    version = write(conn, key, {'star_rating': 4}, group=2)
    assert version == 1
    assets.set_primary(conn, key, '/a.jpg', 2, visibility_sql='1=1')
    state = review.read(conn, key, 'alice', LABELS)
    assert state['values']['star_rating'] == 4 and state['origins']['star_rating'] == 'user'
    assert conn.execute('SELECT * FROM photos ORDER BY path').fetchall() == [('/a.CR2', 2), ('/a.jpg', 5)]


def test_review_source_is_immutable_and_never_inherits_hidden_labels(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    with pytest.raises(assets.AssetConflict):
        review.seed(conn, key, '/a.CR2', 1, visibility_sql='1=1')
    state = review.read(conn, key, 'alice', {'/a.CR2': LABELS['/a.CR2']})
    assert state['source_path'] is None
    assert set(state['values'].values()) == {None}
    with pytest.raises(assets.AssetConflict):
        review.read(conn, key, 'alice', {'/not-a-member.jpg': LABELS['/a.jpg']})


def test_explicit_null_is_distinct_from_inheritance_and_reset_is_versioned(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    version = write(conn, key, {'star_rating': None})
    assert review.read(conn, key, 'alice', LABELS)['values']['star_rating'] is None
    assert review.read(conn, key, 'alice', LABELS)['origins']['star_rating'] == 'user'
    version = review.reset_fields(conn, key, 'alice', 1, version, ['star_rating'], visibility_sql='1=1', file_labels=LABELS,
                                  input_token=review.read(conn, key, 'alice', LABELS)['input_token'])
    assert version == 2
    assert review.read(conn, key, 'alice', LABELS)['values']['star_rating'] == 5
    with pytest.raises(assets.AssetConflict):
        write(conn, key, {'star_rating': 1}, version=0)
    version = review.reset_fields(conn, key, 'alice', 1, version, ['star_rating'], visibility_sql='1=1', file_labels=LABELS,
                                  input_token=review.read(conn, key, 'alice', LABELS)['input_token'])
    assert version == 3


def test_account_scopes_and_agent_origin_are_independent(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    assert write(conn, key, {'star_rating': 5}, origin='agent') == 0
    assert review.read(conn, key, 'alice', LABELS)['origins']['star_rating'] == 'file'
    assert write(conn, key, {'star_rating': 3}, origin='agent') == 1
    assert review.read(conn, key, 'alice', LABELS)['origins']['star_rating'] == 'agent'
    assert review.read(conn, key, 'bob', LABELS)['values']['star_rating'] == 5
    assert write(conn, key, {'star_rating': 3}, version=1) == 2
    assert review.read(conn, key, 'alice', LABELS)['origins']['star_rating'] == 'user'
    assert write(conn, key, {'star_rating': 3}, version=2, origin='agent') == 2
    assert review.read(conn, key, 'alice', LABELS)['origins']['star_rating'] == 'user'


def test_keep_reject_is_one_consistent_decision(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    for patch in [{'is_kept': 1}, {'is_kept': 1, 'is_rejected': 1}]:
        with pytest.raises(assets.AssetConflict):
            write(conn, key, patch)
    version = write(conn, key, {'is_kept': 0, 'is_rejected': 1}, origin='agent')
    assert version == 1
    state = review.read(conn, key, 'alice', LABELS)
    assert state['values']['is_kept'] == 0 and state['values']['is_rejected'] == 1
    assert state['origins']['is_kept'] == state['origins']['is_rejected'] == 'agent'


def test_restart_and_caller_rollback_preserve_review_authority(catalog):
    conn, path, key = catalog
    conn.execute('BEGIN')
    write(conn, key, {'star_rating': 4})
    conn.commit()
    with sqlite3.connect(path) as other:
        other.execute('BEGIN')
        assert review.read(other, key, 'alice', LABELS)['values']['star_rating'] == 4
    conn.execute('BEGIN')
    write(conn, key, {'star_rating': 1}, version=1)
    conn.rollback()
    conn.execute('BEGIN')
    assert review.read(conn, key, 'alice', LABELS)['values']['star_rating'] == 4
    assert review.read(conn, key, 'alice', LABELS)['revision'] == 1


def test_stale_hidden_and_invalid_edits_do_not_mutate_review(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    with pytest.raises(assets.AssetConflict):
        write(conn, key, {'star_rating': 4}, visibility_sql='path != ?', visibility_params=['/a.CR2'])
    for patch in [{'star_rating': True}, {'star_rating': 6}, {'is_favorite': '1'}]:
        with pytest.raises(assets.AssetConflict):
            write(conn, key, patch)
    assert review.read(conn, key, 'alice', LABELS)['revision'] == 0
    assert conn.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0


def test_mid_patch_failure_rolls_back_fields_and_clocks_only(catalog):
    conn, _, key = catalog
    conn.execute("CREATE TRIGGER fail_second_field BEFORE INSERT ON logical_review_fields "
                 "WHEN NEW.field='is_favorite' BEGIN SELECT RAISE(ABORT,'injected'); END")
    conn.execute('BEGIN')
    conn.execute("UPDATE photos SET star_rating=4 WHERE path='/a.jpg'")
    with pytest.raises(sqlite3.IntegrityError):
        write(conn, key, {'star_rating': 3, 'is_favorite': 1})
    assert review.read(conn, key, 'alice', LABELS)['revision'] == 0
    assert conn.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0
    assert conn.execute("SELECT star_rating FROM photos WHERE path='/a.jpg'").fetchone()[0] == 4


def test_direct_writers_advance_only_the_affected_owner_clock(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    write(conn, key, {'star_rating': 4})
    write(conn, key, {'is_favorite': 1}, owner='bob')
    conn.execute("UPDATE logical_review_fields SET value=3 WHERE asset_id=? AND owner='alice'", (key,))
    assert review.read(conn, key, 'alice', LABELS)['revision'] == 2
    assert review.read(conn, key, 'bob', LABELS)['revision'] == 1
    conn.execute("DELETE FROM logical_review_fields WHERE asset_id=? AND owner='alice'", (key,))
    assert review.read(conn, key, 'alice', LABELS)['revision'] == 3
    assert review.read(conn, key, 'bob', LABELS)['revision'] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE logical_review_fields SET owner='alice' WHERE owner='bob'")
    assert review.read(conn, key, 'bob', LABELS)['revision'] == 1


def test_partial_decision_reset_is_refused(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    state = review.read(conn, key, 'alice', LABELS)
    with pytest.raises(assets.AssetConflict):
        review.reset_fields(conn, key, 'alice', 1, 0, ['is_rejected'], visibility_sql='1=1',
                            file_labels=LABELS, input_token=state['input_token'])
    assert review.read(conn, key, 'alice', LABELS)['revision'] == 0


def test_seed_rename_follows_the_member_and_preserves_inheritance(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    conn.execute("UPDATE photos SET path='/renamed.jpg' WHERE path='/a.jpg'")
    labels = {'/renamed.jpg': LABELS['/a.jpg'], '/a.CR2': LABELS['/a.CR2']}
    state = review.read(conn, key, 'alice', labels)
    assert state['source_path'] == '/renamed.jpg'
    assert state['values']['star_rating'] == 5


def test_inherited_file_change_refuses_an_edit_without_logical_version_change(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    before = review.read(conn, key, 'alice', LABELS)
    conn.execute("UPDATE photos SET star_rating=4 WHERE path='/a.jpg'")
    rating = conn.execute("SELECT star_rating FROM photos WHERE path='/a.jpg'").fetchone()[0]
    current = {**LABELS, '/a.jpg': {**LABELS['/a.jpg'], 'star_rating': rating}}
    assert review.read(conn, key, 'alice', current)['revision'] == before['revision'] == 0
    with pytest.raises(assets.AssetConflict, match='Logical review inputs changed'):
        review.set_fields(conn, key, 'alice', 1, 0, {'star_rating': 3}, origin='user',
                          visibility_sql='1=1', file_labels=current, input_token=before['input_token'])
    assert conn.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0
    assert conn.execute("SELECT star_rating FROM photos WHERE path='/a.jpg'").fetchone()[0] == 4


def test_read_requires_a_shared_catalog_snapshot(catalog):
    conn, _, key = catalog
    with pytest.raises(assets.AssetConflict, match='read transaction'):
        review.read(conn, key, 'alice', LABELS)


def test_review_survives_primary_loss_with_one_representation_remaining(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    write(conn, key, {'star_rating': 4})
    conn.execute("DELETE FROM photos WHERE path='/a.jpg'")
    assert conn.execute('SELECT primary_path,revision FROM logical_assets WHERE id=?', (key,)).fetchone() == (None, 2)
    state = review.read(conn, key, 'alice', {'/a.CR2': LABELS['/a.CR2']})
    assert state['values']['star_rating'] == 4
    assert state['source_path'] is None
    assert state['origins']['is_rejected'] == 'unknown'
    assets.set_primary(conn, key, '/a.CR2', 2, visibility_sql='1=1')
    assert review.read(conn, key, 'alice', {'/a.CR2': LABELS['/a.CR2']})['values']['star_rating'] == 4


def test_decision_is_one_atomic_storage_value_and_legacy_file_flags_are_not_rewritten(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    contradictory = {**LABELS, '/a.jpg': {**LABELS['/a.jpg'], 'is_rejected': 1}}
    state = review.read(conn, key, 'alice', contradictory)
    assert state['values']['is_kept'] == 0 and state['values']['is_rejected'] == 1
    write(conn, key, {'is_kept': 1, 'is_rejected': 0})
    assert conn.execute('SELECT field,value FROM logical_review_fields').fetchall() == [('decision', 1)]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE logical_review_fields SET value=3 WHERE field='decision'")
    state = review.read(conn, key, 'alice', LABELS)
    assert state['values']['is_kept'] == 1 and state['values']['is_rejected'] == 0


def test_deleted_seed_cannot_adopt_a_new_photo_reusing_its_path(catalog):
    conn, _, key = catalog
    conn.execute('BEGIN')
    conn.execute("DELETE FROM photos WHERE path='/a.jpg'")
    conn.execute("INSERT INTO photos VALUES ('/a.jpg',1)")
    conn.execute("UPDATE photos SET path='/unrelated.jpg' WHERE path='/a.jpg'")
    assert conn.execute('SELECT photo_path FROM logical_review_seeds WHERE asset_id=?', (key,)).fetchone() == (None,)
    state = review.read(conn, key, 'alice', {'/a.CR2': LABELS['/a.CR2'], '/unrelated.jpg': LABELS['/a.jpg']})
    assert state['source_path'] is None
    assert set(state['values'].values()) == {None}
    with pytest.raises(assets.AssetConflict):
        review.seed(conn, key, '/a.CR2', 2, visibility_sql='1=1')


@pytest.mark.parametrize('token', ['ñ' * 64, 'G' * 64, 'a' * 63, None, '0' * 64])
def test_malformed_input_tokens_refuse_without_storage_side_effects(catalog, token):
    conn, _, key = catalog
    conn.execute('BEGIN')
    with pytest.raises(assets.AssetConflict):
        review.set_fields(conn, key, 'alice', 1, 0, {'star_rating': 3}, origin='user',
                          visibility_sql='1=1', file_labels=LABELS, input_token=token)
    assert review.read(conn, key, 'alice', LABELS)['revision'] == 0
    assert conn.execute('SELECT COUNT(*) FROM logical_review_fields').fetchone()[0] == 0


def test_row_factory_records_are_serialized_into_the_input_precondition(catalog):
    conn, _, key = catalog
    conn.row_factory = sqlite3.Row
    conn.execute('BEGIN')
    write(conn, key, {'star_rating': 3})
    current = review.read(conn, key, 'alice', LABELS)
    assert len(current['input_token']) == 64
    assert current['values']['star_rating'] == 3


def test_input_precondition_is_bound_to_the_actual_database(catalog, tmp_path):
    conn, _, key = catalog
    conn.execute('BEGIN')
    before = review.read(conn, key, 'alice', LABELS)
    copy = sqlite3.connect(tmp_path / 'copy.db')
    try:
        conn.backup(copy)
        copy.execute('BEGIN')
        with pytest.raises(assets.AssetConflict, match='inputs changed'):
            review.set_fields(copy, key, 'alice', 1, 0, {'star_rating': 3}, origin='user',
                              visibility_sql='1=1', file_labels=LABELS, input_token=before['input_token'])
        assert review.read(copy, key, 'alice', LABELS)['revision'] == 0
        assert review.read(conn, key, 'alice', LABELS)['revision'] == 0
    finally:
        copy.close()
