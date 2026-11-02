"""Stable hierarchy identities are separate from literal flat keywords."""

import sqlite3

import pytest

from db.keyword_hierarchy import (
    HierarchyError, assign_node, assign_path, change_node, create_keyword_hierarchy_schema,
    delete_branch, ensure_path, normalize_path, photo_hierarchies, plan_path_import, remove_assignment,
)


@pytest.fixture
def catalog():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE photos(path TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE photo_manual_tags(photo_path TEXT,tag TEXT)')
        conn.executemany('INSERT INTO photos(path) VALUES(?)', [('a',), ('b',)])
        conn.execute("INSERT INTO photo_manual_tags VALUES('a','Animals/Cat')")
        create_keyword_hierarchy_schema(conn)
        conn.commit()
        yield conn


def snapshot(conn):
    return list(conn.iterdump())


def test_full_path_identity_unicode_duplicate_leaves_and_no_implicit_ancestor_assignments(catalog):
    domestic, _ = assign_path(catalog, 'a', ['Animals', 'Domestic', 'Cat'], source='xmp', imported_path='animals|DOMESTIC|Cat')
    wild, _ = assign_path(catalog, 'a', ['Animals', 'Wild', 'Cat'])
    literal = ensure_path(catalog, ['Animals/Cat'])
    assert len({domestic, wild, literal}) == 3
    assert ensure_path(catalog, ['Cafe\u0301']) == ensure_path(catalog, ['CAFÉ'])
    result = photo_hierarchies(catalog, 'a')
    assert [row['exported_path'] for row in result] == ['animals|DOMESTIC|Cat', 'Animals|Wild|Cat']
    assert {row['node_id'] for row in result} == {domestic, wild}
    assert catalog.execute('SELECT COUNT(*) FROM photo_keyword_nodes').fetchone()[0] == 2
    assert catalog.execute('SELECT * FROM photo_manual_tags').fetchall() == [('a', 'Animals/Cat')]


def test_rename_move_preserve_ids_and_do_not_restore_old_imported_assignments(catalog):
    leaf, _ = assign_path(catalog, 'a', ['Animals', 'Wild', 'Cat'], source='xmp', imported_path='Animals|Wild|Cat')
    parent = catalog.execute('SELECT parent_id FROM keyword_nodes WHERE id=?', (leaf,)).fetchone()[0]
    assert change_node(catalog, parent, writable_paths={'a'}, name='Wildlife', created_by='alice') == ['a']
    root = ensure_path(catalog, ['Archive'])
    assert change_node(catalog, parent, writable_paths={'a'}, parent_id=root, created_by='alice') == ['a']
    assert photo_hierarchies(catalog, 'a') == [
        {'node_id': leaf, 'segments': ['Archive', 'Wildlife', 'Cat'], 'source': 'user', 'exported_path': 'Archive|Wildlife|Cat'}]
    old, changed = assign_path(catalog, 'a', ['Animals', 'Wild', 'Cat'], source='xmp', imported_path='Animals|Wild|Cat')
    assert old != leaf and changed is False
    assert len(photo_hierarchies(catalog, 'a')) == 1
    assert assign_node(catalog, 'a', old) is True  # Explicit reassign clears the deletion record.
    assert len(photo_hierarchies(catalog, 'a')) == 2


def test_shared_branch_cannot_partially_rename_or_delete_hidden_assignments(catalog):
    leaf, _ = assign_path(catalog, 'a', ['Animals', 'Cat'])
    assign_node(catalog, 'b', leaf)
    before = snapshot(catalog)
    for operation in [lambda: change_node(catalog, leaf, writable_paths={'a'}, name='Kitten'),
                      lambda: delete_branch(catalog, leaf, writable_paths={'a'})]:
        with pytest.raises(HierarchyError, match='complete branch'):
            operation()
        assert snapshot(catalog) == before


def test_cycles_collisions_and_overdepth_moves_refuse_before_mutation(catalog):
    leaf = ensure_path(catalog, ['Animals', 'Cat'])
    dog = ensure_path(catalog, ['Animals', 'Dog'])
    root = catalog.execute('SELECT parent_id FROM keyword_nodes WHERE id=?', (leaf,)).fetchone()[0]
    deep = ensure_path(catalog, [f'Level{i}' for i in range(16)])
    before = snapshot(catalog)
    for operation in [lambda: change_node(catalog, root, writable_paths=set(), parent_id=leaf),
                      lambda: change_node(catalog, dog, writable_paths=set(), name='CAT'),
                      lambda: change_node(catalog, root, writable_paths=set(), parent_id=deep)]:
        with pytest.raises(HierarchyError):
            operation()
        assert snapshot(catalog) == before


@pytest.mark.parametrize('failure', ['ABORT', 'ROLLBACK'])
def test_late_assignment_failure_rolls_back_node_and_deletion_records(catalog, failure):
    leaf, _ = assign_path(catalog, 'a', ['Animals', 'Cat'], source='xmp', imported_path='Animals|Cat')
    assign_node(catalog, 'b', leaf, source='xmp', imported_path='Animals|Cat')
    catalog.execute("CREATE TRIGGER hierarchy_failure BEFORE UPDATE ON photo_keyword_nodes "
                    f"WHEN OLD.photo_path='b' BEGIN SELECT RAISE({failure},'fixture'); END")
    before = snapshot(catalog)
    with pytest.raises(sqlite3.IntegrityError, match='fixture'):
        change_node(catalog, leaf, writable_paths={'a', 'b'}, name='Kitten')
    assert snapshot(catalog) == before


@pytest.mark.parametrize('foreign_keys', [False, True])
def test_photo_move_delete_and_branch_delete_never_delete_another_photo(catalog, foreign_keys):
    catalog.execute(f'PRAGMA foreign_keys={int(foreign_keys)}')
    leaf, _ = assign_path(catalog, 'a', ['Animals', 'Cat'])
    assert remove_assignment(catalog, 'a', leaf)
    assert assign_node(catalog, 'a', leaf, source='xmp', imported_path='Animals|Cat') is False
    assert assign_node(catalog, 'a', leaf) is True
    catalog.execute("UPDATE photos SET path='moved' WHERE path='a'")
    assert photo_hierarchies(catalog, 'a') == []
    assert photo_hierarchies(catalog, 'moved')[0]['node_id'] == leaf
    assert delete_branch(catalog, leaf, writable_paths={'moved'}) == ['moved']
    assert catalog.execute('SELECT path FROM photos ORDER BY path').fetchall() == [('b',), ('moved',)]
    catalog.execute("DELETE FROM photos WHERE path='moved'")
    assert catalog.execute('SELECT * FROM keyword_assignment_deletions').fetchall() == []


def test_assignment_cap_rolls_back_new_vocabulary_and_user_origin_survives_import(catalog):
    for i in range(50):
        assign_path(catalog, 'a', [f'Tag{i}'])
    before = snapshot(catalog)
    with pytest.raises(HierarchyError, match='at most 50'):
        assign_path(catalog, 'a', ['New', 'Branch'])
    assert snapshot(catalog) == before
    node = ensure_path(catalog, ['Tag0'])
    assert assign_node(catalog, 'a', node, source='xmp', imported_path='TAG0') is False
    assert next(row for row in photo_hierarchies(catalog, 'a') if row['node_id'] == node)['source'] == 'user'


def test_old_readonly_schema_is_not_migrated_and_invalid_paths_do_not_write(catalog):
    before = snapshot(catalog)
    for path in [['a|b'], ['a', ''], ['a\u202eb'], ['x'] * 17, 'Animals/Cat']:
        with pytest.raises(HierarchyError):
            normalize_path(path)
        assert snapshot(catalog) == before
    with sqlite3.connect(':memory:') as old:
        old.execute('CREATE TABLE photos(path TEXT PRIMARY KEY)')
        old.execute('PRAGMA query_only=ON')
        before = snapshot(old)
        assert photo_hierarchies(old, 'a') == []
        assert snapshot(old) == before


@pytest.mark.parametrize('operation', ['ensure', 'preview'])
def test_existing_keyword_path_lookup_does_not_scan_the_vocabulary(catalog, operation):
    leaf = ensure_path(catalog, ['Animals', 'Cat'])
    catalog.executemany('INSERT INTO keyword_nodes VALUES (?, NULL, ?, ?)',
                        [(f'archive-{i}', f'Archive {i}', f'archive {i}') for i in range(5000)])
    catalog.commit()
    before = catalog.total_changes
    steps = 0

    def budget():
        nonlocal steps
        steps += 100
        return int(steps > 5000)

    catalog.set_progress_handler(budget, 100)
    try:
        if operation == 'ensure':
            assert ensure_path(catalog, ['ANIMALS', 'cat']) == leaf
        else:
            proposed, diagnostics = plan_path_import(catalog, 'a', ['ANIMALS|cat'])
            assert proposed == [(['ANIMALS', 'cat'], 'ANIMALS|cat')]
            assert diagnostics == []
    finally:
        catalog.set_progress_handler(None, 0)
    assert catalog.total_changes == before
