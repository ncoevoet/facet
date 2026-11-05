"""Viewer refresh preserves hierarchy identity without replaying local authority."""

import hashlib
import sqlite3
import threading
from pathlib import Path

import pytest

from db.keyword_hierarchy import (
    HierarchyError, assign_node, assign_path, change_node, photo_hierarchies, remove_assignment,
)
from db.keyword_hierarchy_sync import prepare_hierarchy_sync
from db.maintenance import export_viewer_db
from db.schema import init_database


@pytest.fixture
def library(tmp_path):
    source = tmp_path / "scan's café.db"
    viewer = tmp_path / 'viewer.db'
    init_database(str(source), build_photo_indexes=False)
    with sqlite3.connect(source) as conn:
        conn.executemany('INSERT INTO photos(path,filename,caption) VALUES(?,?,?)',
                         [('a', 'a.jpg', 'before'), ('b', 'b.jpg', 'before')])
        leaf, _ = assign_path(conn, 'a', ['Animals', 'Cat'], source='xmp', imported_path='ANIMALS|Cat', created_by='private-actor')
        assign_node(conn, 'b', leaf)
    return source, viewer, leaf


def export(library):
    source, viewer, _ = library
    return export_viewer_db(str(source), str(viewer), verbose=False)


def state(conn):
    return {name: conn.execute(f'SELECT * FROM {name} ORDER BY 1,2').fetchall() for name in
            ['keyword_nodes', 'photo_keyword_nodes', 'keyword_assignment_deletions', 'keyword_node_edits', 'keyword_node_baselines']}


def test_full_export_keeps_ids_spelling_and_origin_without_copying_edit_authority(library):
    source, viewer, leaf = library
    with sqlite3.connect(source) as conn:
        removed, _ = assign_path(conn, 'a', ['Old', 'Keyword'])
        remove_assignment(conn, 'a', removed)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    export(library)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    with sqlite3.connect(viewer) as conn:
        assert photo_hierarchies(conn, 'a') == [{'node_id': leaf, 'segments': ['Animals', 'Cat'],
            'source': 'catalog', 'exported_path': 'ANIMALS|Cat'}]
        assert conn.execute('SELECT source,origin_source,created_by FROM photo_keyword_nodes WHERE photo_path=\'a\'').fetchone() == ('catalog', 'xmp', None)
        assert conn.execute('SELECT source,origin_source,created_by FROM photo_keyword_nodes WHERE photo_path=\'b\'').fetchone() == ('catalog', 'user', None)
        assert conn.execute('SELECT COUNT(*) FROM keyword_node_edits').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM keyword_assignment_deletions').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM keyword_node_baselines').fetchone()[0] == conn.execute('SELECT COUNT(*) FROM keyword_nodes').fetchone()[0]


def test_untouched_baseline_definitions_and_assignments_follow_current_source(library):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(source) as conn:
        change_node(conn, leaf, name='Kitten', writable_paths={'a', 'b'})
        remove_assignment(conn, 'b', leaf)
    export(library)
    with sqlite3.connect(viewer) as conn:
        assert photo_hierarchies(conn, 'a')[0]['segments'] == ['Animals', 'Kitten']
        assert photo_hierarchies(conn, 'b') == []
        assert conn.execute('SELECT COUNT(*) FROM keyword_node_edits').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM keyword_assignment_deletions').fetchone()[0] == 0


def test_incremental_export_syncs_hierarchy_and_new_ai_edit_links_together(library):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(source) as conn:
        change_node(conn, leaf, name='Kitten', writable_paths={'a', 'b'})
        conn.execute("INSERT INTO photos(path,filename) VALUES('edit','edit.jpg')")
        conn.execute("INSERT INTO photo_ai_edits(edit_path,source_path,tool,revision) VALUES('edit','a','test',1)")
    for _ in range(2):
        export(library)
        with sqlite3.connect(viewer) as conn:
            assert photo_hierarchies(conn, 'a')[0]['segments'] == ['Animals', 'Kitten']
            assert conn.execute('SELECT edit_path,source_path,tool,revision FROM photo_ai_edits').fetchall() == [
                ('edit', 'a', 'test', 1)]
            assert conn.execute('SELECT COUNT(*) FROM keyword_node_edits').fetchone()[0] == 0


def test_source_deletion_and_recreation_replace_unedited_baseline(library):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(source) as conn:
        conn.execute('DELETE FROM photo_keyword_nodes WHERE node_id=?', (leaf,))
        conn.execute('DELETE FROM keyword_nodes WHERE id=?', (leaf,))
        replacement, _ = assign_path(conn, 'a', ['Animals', 'Cat'])
        assert replacement != leaf
    export(library)
    with sqlite3.connect(viewer) as conn:
        assert photo_hierarchies(conn, 'a')[0]['node_id'] == replacement
        assert conn.execute('SELECT 1 FROM keyword_nodes WHERE id=?', (leaf,)).fetchone() is None
        assert conn.execute('SELECT 1 FROM keyword_node_baselines WHERE node_id=?', (leaf,)).fetchone() is None


def test_source_deletion_preserves_local_assignment_and_ancestors(library):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(viewer) as conn:
        conn.execute("UPDATE photo_keyword_nodes SET source='user' WHERE photo_path='a' AND node_id=?", (leaf,))
    with sqlite3.connect(source) as conn:
        conn.execute('DELETE FROM photo_keyword_nodes WHERE node_id=?', (leaf,))
        root = conn.execute('SELECT parent_id FROM keyword_nodes WHERE id=?', (leaf,)).fetchone()[0]
        conn.execute('DELETE FROM keyword_nodes WHERE id=?', (leaf,))
        conn.execute('DELETE FROM keyword_nodes WHERE id=?', (root,))
    export(library)
    with sqlite3.connect(viewer) as conn:
        assert photo_hierarchies(conn, 'a')[0]['segments'] == ['Animals', 'Cat']
        assert photo_hierarchies(conn, 'b') == []


def test_source_deletion_preserves_locally_edited_definition(library):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(viewer) as conn:
        change_node(conn, leaf, name='Viewer cat', writable_paths={'a', 'b'})
    with sqlite3.connect(source) as conn:
        conn.execute('DELETE FROM photo_keyword_nodes WHERE node_id=?', (leaf,))
        conn.execute('DELETE FROM keyword_nodes WHERE id=?', (leaf,))
    export(library)
    with sqlite3.connect(viewer) as conn:
        assert conn.execute('SELECT name FROM keyword_nodes WHERE id=?', (leaf,)).fetchone() == ('Viewer cat',)


def test_local_rename_and_id_bound_removal_survive_source_rename_and_new_photos(library):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(viewer) as conn:
        root = conn.execute('SELECT parent_id FROM keyword_nodes WHERE id=?', (leaf,)).fetchone()[0]
        change_node(conn, root, name='Viewer animals', writable_paths={'a', 'b'})
        remove_assignment(conn, 'b', leaf)
    with sqlite3.connect(source) as conn:
        change_node(conn, root, name='Scanner animals', writable_paths={'a', 'b'})
        conn.execute("INSERT INTO photos(path,filename) VALUES('c','c.jpg')")
        assign_node(conn, 'c', leaf)
    export(library)
    with sqlite3.connect(viewer) as conn:
        assert photo_hierarchies(conn, 'a')[0]['segments'] == ['Viewer animals', 'Cat']
        assert photo_hierarchies(conn, 'a')[0]['source'] == 'user'
        assert photo_hierarchies(conn, 'b') == []
        assert photo_hierarchies(conn, 'c')[0]['segments'] == ['Viewer animals', 'Cat']
        assert photo_hierarchies(conn, 'c')[0]['source'] == 'catalog'


@pytest.mark.parametrize('late_change', ['source', 'viewer'])
def test_prepared_snapshot_is_coherent_and_late_viewer_edits_are_rechecked(library, late_change):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(viewer) as conn:
        conn.execute('ATTACH DATABASE ? AS src', (str(source),))
        captured = prepare_hierarchy_sync(conn)
        try:
            if late_change == 'source':
                with sqlite3.connect(source) as writer:
                    change_node(writer, leaf, name='After snapshot', writable_paths={'a', 'b'})
                    assign_path(writer, 'a', ['New after snapshot'])
            else:
                change_node(conn, leaf, name='Viewer late edit', writable_paths={'a', 'b'})
            captured.apply(conn)
            assert photo_hierarchies(conn, 'a')[0]['segments'] == ['Animals', 'Cat' if late_change == 'source' else 'Viewer late edit']
            assert len(photo_hierarchies(conn, 'a')) == 1
        finally:
            captured.close(conn)


def test_source_wal_commit_during_capture_cannot_mix_old_nodes_with_new_assignments(library, monkeypatch):
    import db.keyword_hierarchy_sync as sync
    source, viewer, leaf = library
    export(library)
    entered, committed = threading.Event(), threading.Event()
    errors = []
    original = sync._graph

    def graph(conn, *args, **kwargs):
        result = original(conn, *args, **kwargs)
        if kwargs.get('schema') == 'src':
            entered.set()
            assert committed.wait(5)
        return result

    def write():
        try:
            assert entered.wait(5)
            with sqlite3.connect(source) as conn:
                conn.execute('BEGIN IMMEDIATE')
                change_node(conn, leaf, name='New committed name', writable_paths={'a', 'b'})
                remove_assignment(conn, 'b', leaf)
        except BaseException as error:
            errors.append(error)
        finally:
            committed.set()

    monkeypatch.setattr(sync, '_graph', graph)
    writer = threading.Thread(target=write)
    writer.start()
    try:
        with sqlite3.connect(viewer) as conn:
            conn.execute('ATTACH DATABASE ? AS src', (str(source),))
            captured = prepare_hierarchy_sync(conn)
            try:
                captured.apply(conn)
                assert photo_hierarchies(conn, 'a')[0]['segments'] == ['Animals', 'Cat']
                assert photo_hierarchies(conn, 'b')[0]['node_id'] == leaf
            finally:
                captured.close(conn)
    finally:
        writer.join(5)
    assert not writer.is_alive() and errors == []
    with sqlite3.connect(source) as conn:
        assert photo_hierarchies(conn, 'a')[0]['segments'] == ['Animals', 'New committed name']
        assert photo_hierarchies(conn, 'b') == []


def test_sibling_name_swap_uses_one_atomic_final_identity_graph(library):
    source, viewer, leaf = library
    with sqlite3.connect(source) as conn:
        dog, _ = assign_path(conn, 'a', ['Animals', 'Dog'])
    export(library)
    with sqlite3.connect(source) as conn:
        change_node(conn, leaf, name='Temporary', writable_paths={'a', 'b'})
        change_node(conn, dog, name='Cat', writable_paths={'a', 'b'})
        change_node(conn, leaf, name='Dog', writable_paths={'a', 'b'})
    export(library)
    with sqlite3.connect(viewer) as conn:
        assert conn.execute('SELECT name FROM keyword_nodes WHERE id=?', (leaf,)).fetchone()[0] == 'Dog'
        assert conn.execute('SELECT name FROM keyword_nodes WHERE id=?', (dog,)).fetchone()[0] == 'Cat'
        assert not any(row[0].startswith('\0') for row in conn.execute('SELECT name_key FROM keyword_nodes'))


def test_different_id_same_path_collision_refuses_before_photo_metadata_update(library):
    source, viewer, _ = library
    export(library)
    with sqlite3.connect(viewer) as conn:
        assign_path(conn, 'a', ['Independent'])
        before = state(conn)
    with sqlite3.connect(source) as conn:
        assign_path(conn, 'a', ['Independent'])
        conn.execute("UPDATE photos SET caption='after' WHERE path='a'")
    with pytest.raises(HierarchyError, match='conflict'):
        export(library)
    with sqlite3.connect(viewer) as conn:
        assert state(conn) == before
        assert conn.execute("SELECT caption FROM photos WHERE path='a'").fetchone()[0] == 'before'


def test_merged_assignment_capacity_is_validated_before_definitions_change(library):
    source, viewer, _ = library
    export(library)
    with sqlite3.connect(viewer) as conn:
        for i in range(49):
            assign_path(conn, 'a', [f'Local{i}'])
        before = state(conn)
    with sqlite3.connect(source) as conn:
        assign_path(conn, 'a', ['Source extra'])
    with pytest.raises(HierarchyError, match='per-photo limit'):
        export(library)
    with sqlite3.connect(viewer) as conn:
        assert state(conn) == before


@pytest.mark.parametrize('failure', ['ABORT', 'ROLLBACK'])
def test_late_merge_failure_rolls_back_nodes_baselines_and_assignment_replacement(library, failure):
    source, viewer, leaf = library
    export(library)
    with sqlite3.connect(source) as conn:
        change_node(conn, leaf, name='Kitten', writable_paths={'a', 'b'})
    with sqlite3.connect(viewer) as conn:
        conn.execute('ATTACH DATABASE ? AS src', (str(source),))
        captured = prepare_hierarchy_sync(conn)
        conn.execute("CREATE TRIGGER reject_copy BEFORE INSERT ON photo_keyword_nodes "
                     f"WHEN NEW.photo_path='b' BEGIN SELECT RAISE({failure},'fixture'); END")
        before = state(conn)
        try:
            with pytest.raises(sqlite3.IntegrityError, match='fixture'):
                captured.apply(conn)
            assert state(conn) == before
        finally:
            captured.close(conn)


def test_export_phase_failure_closes_connection_and_its_temporary_snapshot(library, monkeypatch):
    import db.manual_face_export as faces
    import db.maintenance as maintenance
    source, viewer, _ = library
    export(library)
    original = sqlite3.connect
    tracked = []

    def connect(*args, **kwargs):
        conn = original(*args, **kwargs)
        if str(args[0]) == str(viewer):
            tracked.append(conn)
        return conn

    monkeypatch.setattr(maintenance.sqlite3, 'connect', connect)
    monkeypatch.setattr(faces, 'prepare_person_sync', lambda _: (_ for _ in ()).throw(RuntimeError('later phase fixture')))
    with pytest.raises(RuntimeError, match='later phase fixture'):
        export(library)
    assert tracked
    for conn in tracked:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            conn.execute('SELECT 1')


def test_released_source_without_hierarchy_is_read_without_migration_or_clearing_viewer_data(library, tmp_path):
    _, viewer, _ = library
    export(library)
    old = tmp_path / 'released-v1-23-1.db'
    with sqlite3.connect(old) as conn:
        conn.executescript(Path('tests/fixtures/photo_stacks_v1_23_1_schema.sql').read_text())
        conn.execute("INSERT INTO photos(path,filename) VALUES('a','a.jpg')")
    before = hashlib.sha256(old.read_bytes()).hexdigest()
    with sqlite3.connect(viewer) as conn:
        conn.execute('ATTACH DATABASE ? AS src', (str(old),))
        original = state(conn)
        assert prepare_hierarchy_sync(conn) is None
        assert state(conn) == original
    assert hashlib.sha256(old.read_bytes()).hexdigest() == before
