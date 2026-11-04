"""Explicit catalog erasure must not depend on original-file availability."""
import sqlite3
from contextlib import contextmanager
from unittest import mock

from tests.test_cull import _db, _remaining_paths


@contextmanager
def _connection(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        yield conn
    finally:
        conn.close()


def test_catalog_removal_erases_stored_previews_even_with_deleted_folder(edition_client, tmp_path):
    path = str(tmp_path / 'already-deleted-folder' / 'private.jpg')
    keep = str(tmp_path / 'keep.jpg')
    db = _db(tmp_path, [(path, 1), (keep, 0)])
    with _connection(db) as conn:
        conn.execute('UPDATE photos SET thumbnail = ? WHERE path = ?', (b'private-preview', path))
        conn.execute('INSERT INTO photo_tags(photo_path, tag) VALUES (?, ?)', (path, 'private'))
        conn.commit()
    from api.routers import thumbnails
    cache_key = (path, 64, b'cached')
    thumbnails._resize_cache[cache_key] = b'private-preview'
    with (
        mock.patch('api.routers.export.get_db', lambda: _connection(db)),
        mock.patch('api.routers.export._require_trash_available', side_effect=AssertionError('No disk trash operation')),
        mock.patch('api.routers.export.resolve_photo_disk_path', side_effect=AssertionError('No disk access')),
    ):
        preview = edition_client.post('/api/photo/delete', json={'paths': [path], 'catalog_only': True})
        assert preview.status_code == 200
        assert preview.json()['removed_catalog'] == [path]
        assert path in _remaining_paths(db)
        assert cache_key in thumbnails._resize_cache
        response = edition_client.post('/api/photo/delete', json={
            'paths': [path, path], 'catalog_only': True, 'dry_run': False,
        })
    assert response.status_code == 200
    assert response.json()['removed_catalog'] == [path]
    assert response.json()['trashed'] == 0
    assert _remaining_paths(db) == {keep}
    assert cache_key not in thumbnails._resize_cache
    with _connection(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM photo_tags WHERE photo_path = ?', (path,)).fetchone()[0] == 0


def test_catalog_removal_preserves_original_bytes_and_refuses_scope_expansion(edition_client, tmp_path):
    original = tmp_path / 'original.jpg'
    original.write_bytes(b'original-unchanged')
    path = str(original)
    db = _db(tmp_path, [(path, 0)])
    with mock.patch('api.routers.export.get_db', lambda: _connection(db)):
        refused = edition_client.post('/api/photo/delete', json={
            'paths': [path], 'catalog_only': True, 'dry_run': False, 'include_companions': True,
        })
        assert refused.status_code == 422
        assert path in _remaining_paths(db)
        result = edition_client.post('/api/photo/delete', json={
            'paths': [path, 'not-in-catalog'], 'catalog_only': True, 'dry_run': False,
        })
    assert result.status_code == 200
    assert result.json()['removed_catalog'] == [path]
    assert result.json()['not_found'] == ['not-in-catalog']
    assert original.read_bytes() == b'original-unchanged'


def test_catalog_removal_requires_edition(regular_client):
    assert regular_client.post('/api/photo/delete', json={
        'paths': ['private.jpg'], 'catalog_only': True, 'dry_run': False,
    }).status_code == 403


def test_catalog_removal_refuses_a_bracket_lead_in_preview_and_apply(edition_client, tmp_path):
    lead = str(tmp_path / 'lead.jpg')
    sibling = str(tmp_path / 'sibling.jpg')
    db = _db(tmp_path, [
        (lead, 0, {'sequence_kind': 'bracket', 'sequence_group_id': 1, 'sequence_ev_offset': 0.0}),
        (sibling, 0, {'sequence_kind': 'bracket', 'sequence_group_id': 1, 'sequence_ev_offset': 2.0}),
    ])
    with mock.patch('api.routers.export.get_db', lambda: _connection(db)):
        for dry_run in (True, False):
            response = edition_client.post('/api/photo/delete', json={
                'paths': [lead], 'catalog_only': True, 'dry_run': dry_run,
            })
            assert response.status_code == 200, response.text
            assert response.json()['refused_bracket_lead'] == [lead]
            assert response.json()['removed_catalog'] == []
            assert _remaining_paths(db) == {lead, sibling}


def test_sequence_siblings_resolve_all_groups_in_one_query(tmp_path):
    from api.routers.export import _sequence_siblings

    db = _db(tmp_path, [
        ('a', 0, {'sequence_kind': 'bracket', 'sequence_group_id': 1}),
        ('b', 0, {'sequence_kind': 'bracket', 'sequence_group_id': 1}),
        ('c', 0, {'sequence_kind': 'panorama', 'sequence_group_id': 1}),
        ('d', 0, {'sequence_kind': 'panorama', 'sequence_group_id': 1}),
        ('other', 0, {'sequence_kind': 'bracket', 'sequence_group_id': 2}),
    ])
    with _connection(db) as conn:
        conn.executemany('INSERT INTO photos(path,filename,sequence_kind,sequence_group_id,thumbnail) VALUES (?,?,?,?,?)',
                         [(f'unrelated-{i}', f'{i}.jpg', 'bracket', 100 + i, b'inline-thumbnail') for i in range(1000)])
        conn.execute('ANALYZE')
        statements = []
        conn.set_trace_callback(statements.append)
        result = _sequence_siblings(conn, {'a': ('bracket', 1), 'c': ('panorama', 1)}, {'a', 'c'}, None)
        query = next(statement for statement in statements if statement.lstrip().upper().startswith('SELECT'))
        plan = [row[3] for row in conn.execute('EXPLAIN QUERY PLAN ' + query)]
        assert any('SEARCH photos USING' in detail and 'idx_sequence_kind' in detail for detail in plan), plan
        assert not any(detail.startswith('SCAN photos') for detail in plan), plan
    assert set(result) == {'b', 'd'}
    assert len([statement for statement in statements if statement.lstrip().upper().startswith('SELECT')]) == 1
