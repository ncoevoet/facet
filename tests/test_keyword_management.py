"""Actual preview/apply effects, refusal and rollback on disposable catalog data."""

import sqlite3
from pathlib import Path

import pytest

from api import config
from db import DEFAULT_DB_PATH
from db.keyword_hierarchy import assign_node, assign_path, photo_hierarchies

ROOT = '/api/manual_tags/hierarchy'


@pytest.fixture
def owned(tmp_path, seed_photos_prefix, monkeypatch):
    photos = [tmp_path / 'public' / f'{index}.jpg' for index in range(2)] + [tmp_path / 'private' / 'hidden.jpg']
    for path in photos:
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'original bytes')
    seed_photos_prefix(str(tmp_path) + '/', [{'path': str(path), 'filename': path.name, 'tags': 'machine'} for path in photos])
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {owner: {'directories': [str(photos[0].parent)]} for owner in ('test', 'u1')})
    paths = list(map(str, photos))
    label = 'Catalog-' + tmp_path.name
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        shared, _ = assign_path(conn, paths[0], [label, 'Animals', 'Domestic', 'Cat'], source='xmp',
                                imported_path=label + '|Animals|Domestic|Cat')
        assign_node(conn, paths[2], shared)
        private, _ = assign_path(conn, paths[1], [label, 'Animals', 'Wild', 'Cat'])
        destination, _ = assign_path(conn, paths[0], [label, 'Collections'])
        conn.execute("INSERT INTO photo_manual_tags(photo_path,tag,source) VALUES(?,'animals/cat','user')", (paths[0],))
    return paths, label, shared, private, destination


def capture(client, **request):
    response = client.post(ROOT + '/preview', json=request)
    assert response.status_code == 200, response.text
    assert response.headers['Cache-Control'] == 'no-store'
    return response.json()


def apply(client, preview):
    return client.post(ROOT + '/apply', json={**preview['request'], 'preview_token': preview['preview_token']})


def snapshot():
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        return list(conn.iterdump())


def test_create_assign_preview_is_readonly_and_exact_targets_keep_flat_ai_files_unchanged(edition_client, owned):
    paths, label, _, _, _ = owned
    before = snapshot()
    originals = [Path(path).read_bytes() for path in paths]
    preview = capture(edition_client, action='create_assign', segments=[label, 'Places', 'City, Coast'], paths=paths[:2])
    assert snapshot() == before
    assert preview['new_assignments'] == 2 and preview['definition_change'] is None
    assert preview['paths'] == sorted(paths[:2])
    result = apply(edition_client, preview)
    assert result.status_code == 200, result.text
    assert (result.json()['target_photos'], result.json()['affected_photos'], result.json()['changed_assignments']) == (2, 2, 2)
    node = result.json()['node_id']
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT photo_path FROM photo_keyword_nodes WHERE node_id=? ORDER BY photo_path', (node,)).fetchall() == [(path,) for path in sorted(paths[:2])]
        assert all(row[0] == 'machine' for row in conn.execute('SELECT tags FROM photos WHERE path IN (?,?,?)', paths))
        assert conn.execute('SELECT tag FROM photo_manual_tags WHERE photo_path=?', (paths[0],)).fetchall() == [('animals/cat',)]
    assert [Path(path).read_bytes() for path in paths] == originals


def test_hidden_branch_structural_changes_refuse_without_disclosing_hidden_photo_or_partial_writes(edition_client, owned):
    paths, _, shared, _, destination = owned
    before = snapshot()
    for request in [dict(action='rename', node_id=shared, name='Kitten'),
                    dict(action='move', node_id=shared, parent_id=destination), dict(action='delete_branch', node_id=shared)]:
        response = edition_client.post(ROOT + '/preview', json=request)
        assert response.status_code == 409, response.text
        assert paths[2] not in response.text
        assert snapshot() == before
    response = edition_client.post(ROOT + '/preview', json={'action': 'assign', 'node_id': shared, 'paths': [paths[0], paths[2]]})
    assert response.status_code == 409 and snapshot() == before


def test_typed_paths_do_not_disclose_hidden_definitions_or_first_spelling_before_assignment(edition_client, owned, monkeypatch):
    paths, _, _, _, _ = owned
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assign_path(conn, paths[2], ['Secret FAMILY'])
    before = snapshot()
    hidden = capture(edition_client, action='create_assign', segments=['secret family'], paths=[paths[0]])
    unknown = capture(edition_client, action='create_assign', segments=['brand new family'], paths=[paths[0]])
    assert hidden['after_path'] == ['secret family']
    assert hidden['definition_change'] is unknown['definition_change'] is None
    assert hidden['new_assignments'] == unknown['new_assignments'] == 1
    assert snapshot() == before
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        total = conn.execute('SELECT COUNT(*) FROM keyword_nodes').fetchone()[0]
    monkeypatch.setattr('api.keyword_management.MAX_NODES', total)
    for segments in [['secret family'], ['brand new family']]:
        refused = edition_client.post(ROOT + '/preview', json={'action': 'create_assign', 'segments': segments, 'paths': [paths[0]]})
        assert refused.status_code == 422 and 'supported node limit' in refused.text
    assert snapshot() == before


def test_rename_move_and_delete_preserve_identity_then_remove_only_taxonomy(edition_client, owned):
    paths, label, _, node, destination = owned
    renamed = capture(edition_client, action='rename', node_id=node, name='Wild cat')
    assert renamed['before_path'] == [label, 'Animals', 'Wild', 'Cat']
    assert renamed['after_path'] == [label, 'Animals', 'Wild', 'Wild cat']
    assert renamed['paths'] == [paths[1]]
    assert apply(edition_client, renamed).json()['node_id'] == node
    moved = capture(edition_client, action='move', node_id=node, parent_id=destination)
    assert moved['after_path'] == [label, 'Collections', 'Wild cat']
    assert apply(edition_client, moved).json()['node_id'] == node
    deleted = capture(edition_client, action='delete_branch', node_id=node)
    result = apply(edition_client, deleted)
    assert result.status_code == 200 and result.json()['node_id'] is None
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT 1 FROM keyword_nodes WHERE id=?', (node,)).fetchone() is None
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE path IN (?,?,?)', paths).fetchone()[0] == 3
        assert conn.execute('SELECT 1 FROM keyword_assignment_deletions WHERE photo_path=? AND node_id=?', (paths[1], node)).fetchone()
    assert all(Path(path).read_bytes() == b'original bytes' for path in paths)


def test_remove_is_direct_only_and_preview_changes_never_retarget_or_blindly_replay(edition_client, owned):
    paths, _, shared, _, _ = owned
    selected = capture(edition_client, action='remove', node_id=shared, paths=[paths[0]])
    altered = {**selected['request'], 'paths': [paths[1]], 'preview_token': selected['preview_token']}
    before = snapshot()
    assert edition_client.post(ROOT + '/apply', json=altered).status_code == 409
    assert snapshot() == before
    result = apply(edition_client, selected)
    assert result.status_code == 200 and result.json()['changed_assignments'] == 1
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT photo_path FROM photo_keyword_nodes WHERE node_id=?', (shared,)).fetchall() == [(paths[2],)]
    assert apply(edition_client, selected).status_code == 404  # It is no longer a visible concept, not a new target.


@pytest.mark.parametrize('failure', ['ABORT', 'ROLLBACK'])
def test_late_failure_rolls_back_new_nodes_and_all_prior_assignments(edition_client, owned, failure):
    paths, label, _, _, _ = owned
    captured = capture(edition_client, action='create_assign', segments=[label, 'Rollback target'], paths=paths[:2])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        # Trigger DDL cannot bind parameters; let SQLite quote Windows paths.
        target = conn.execute('SELECT quote(?)', (paths[1],)).fetchone()[0]
        conn.execute('CREATE TRIGGER hierarchy_test_failure BEFORE INSERT ON photo_keyword_nodes '
                     f"WHEN NEW.photo_path={target} BEGIN SELECT RAISE({failure},'fixture'); END")
    try:
        before = snapshot()
        response = apply(edition_client, captured)
        assert response.status_code == 503, response.text
        assert snapshot() == before
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DROP TRIGGER hierarchy_test_failure')


def test_assignment_reassertion_clears_removal_intent_and_readonly_cannot_prepare_writes(edition_client, regular_client, owned):
    paths, _, _, node, _ = owned
    assert regular_client.post(ROOT + '/preview', json={'action': 'remove', 'node_id': node, 'paths': [paths[1]]}).status_code == 403
    capture1 = capture(edition_client, action='rename', node_id=node, name='Reasserted')
    assert apply(edition_client, capture1).status_code == 200
    reassigned = capture(edition_client, action='assign', node_id=node, paths=[paths[1]])
    assert reassigned['new_assignments'] == 0 and reassigned['updated_assignments'] == 1
    result = apply(edition_client, reassigned)
    assert result.status_code == 200 and result.json()['affected_photos'] == 1
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM keyword_assignment_deletions WHERE photo_path=? AND node_id=?', (paths[1], node)).fetchone()[0] == 0
        assert photo_hierarchies(conn, paths[1])[0]['node_id'] == node
