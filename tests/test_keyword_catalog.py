"""Keyword discovery and captured assignment edits use disposable catalog/files."""

import sqlite3
from pathlib import Path

import pytest

from api import config
from db import DEFAULT_DB_PATH

ROOT = '/api/manual_tags'


@pytest.fixture
def keywords(tmp_path, seed_photos_prefix):
    paths = [tmp_path / 'public' / f'{i}.jpg' for i in range(3)] + [tmp_path / 'private' / '4.jpg']
    for path in paths:
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'original bytes')
    seed_photos_prefix(str(tmp_path) + '/', [
        {'path': str(path), 'filename': path.name, 'tags': 'destination' if i == 2 else 'ai-only'}
        for i, path in enumerate(paths)
    ])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.executemany('INSERT INTO photo_manual_tags(photo_path,tag,source,created_at) VALUES(?,?,?,?)', [
            (str(path), 'source', 'xmp', '2001-01-01') for path in paths
        ] + [(str(paths[1]), 'destination', 'xmp', '2002-01-01'),
             (str(paths[0]), 'animals/cat', 'user', '2003-01-01'),
             (str(paths[0]), 'zoo/cat', 'user', '2003-01-01'),
             (str(paths[0]), 'café', 'xmp', '2003-01-01')])
    return list(map(str, paths))


def assignments(paths):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        return conn.execute('SELECT photo_path,tag,source,created_by,created_at FROM photo_manual_tags '
                            f'WHERE photo_path IN ({",".join("?" * len(paths))}) ORDER BY photo_path,tag', paths).fetchall()


def test_catalog_pages_exact_literals_unicode_search_counts_and_readonly(regular_client, keywords):
    before = assignments(keywords)
    first = regular_client.get(ROOT + '/catalog', params={'limit': 2})
    assert first.status_code == 200, first.text
    assert first.headers['Cache-Control'] == 'no-store'
    result = first.json()
    all_items = result['items']
    # Five fixture names at two per page require exactly two further pages.
    for _ in range(2):
        assert result['next_after'] is not None
        response = regular_client.get(ROOT + '/catalog', params={'limit': 2, 'after': result['next_after']})
        assert response.status_code == 200, response.text
        result = response.json()
        all_items.extend(result['items'])
    assert result['next_after'] is None
    assert [item['tag'] for item in all_items] == ['animals/cat', 'café', 'destination', 'source', 'zoo/cat']
    assert next(item for item in all_items if item['tag'] == 'source') == {
        'tag': 'source', 'count': 4, 'typed': 0, 'imported': 4, 'unrecorded': 0}
    searched = regular_client.get(ROOT + '/catalog', params={'search': 'Cafe\u0301'}).json()
    assert [item['tag'] for item in searched['items']] == ['café']
    assert regular_client.get(ROOT + '/catalog', params={'search': '%'}).json()['items'] == []
    assert regular_client.post(ROOT + '/manage/preview', json={'source': 'source', 'target': 'new'}).status_code == 403
    assert assignments(keywords) == before


def test_rename_preview_and_apply_merges_manual_and_ai_without_changing_files_or_hidden_photos(edition_client, keywords, monkeypatch):
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': [str(Path(keywords[0]).parent)]}})
    before = assignments(keywords)
    catalog = edition_client.get(ROOT + '/catalog', params={'search': 'source'}).json()
    assert catalog['items'] == [{'tag': 'source', 'count': 3, 'typed': 0, 'imported': 3, 'unrecorded': 0}]
    preview = edition_client.post(ROOT + '/manage/preview', json={'source': ' Source ', 'target': 'Destination'})
    assert preview.status_code == 200, preview.text
    captured = preview.json()
    assert captured['paths'] == keywords[:3]
    assert (captured['renamed'], captured['merged'], captured['ai_matches']) == (1, 1, 1)
    assert assignments(keywords) == before
    assert 'created_by' not in preview.text and keywords[3] not in preview.text
    applied = edition_client.post(ROOT + '/manage/apply', json={
        'source': captured['source'], 'target': captured['target'], 'preview_token': captured['preview_token']})
    assert applied.status_code == 200 and applied.json()['changed'] == 3, applied.text
    rows = assignments(keywords)
    assert (keywords[1], 'destination', 'xmp', None, '2002-01-01') in rows
    assert (keywords[3], 'source', 'xmp', None, '2001-01-01') in rows
    assert any(row[:3] == (keywords[0], 'destination', 'user') for row in rows)
    assert not any(row[0] == keywords[2] and row[1] in ('source', 'destination') for row in rows)
    assert all(Path(path).read_bytes() == b'original bytes' for path in keywords)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT tags FROM photos WHERE path=?', (keywords[2],)).fetchone()[0] == 'destination'


def test_changed_assignments_or_operation_refuse_before_first_write(edition_client, keywords):
    captured = edition_client.post(ROOT + '/manage/preview', json={'source': 'source', 'target': 'new'}).json()
    body = {'source': 'source', 'target': 'different', 'preview_token': captured['preview_token']}
    before = assignments(keywords)
    assert edition_client.post(ROOT + '/manage/apply', json=body).status_code == 409
    assert assignments(keywords) == before
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("UPDATE photo_manual_tags SET created_at='2026-01-01' WHERE photo_path=? AND tag='source'", (keywords[1],))
    before = assignments(keywords)
    body['target'] = 'new'
    assert edition_client.post(ROOT + '/manage/apply', json=body).status_code == 409
    assert assignments(keywords) == before


def test_removing_assignments_does_not_delete_photos_or_literal_siblings(edition_client, keywords):
    captured = edition_client.post(ROOT + '/manage/preview', json={'source': 'animals/cat'}).json()
    assert captured['removed'] == 1 and captured['renamed'] == 0
    response = edition_client.post(ROOT + '/manage/apply', json={'source': 'animals/cat', 'preview_token': captured['preview_token']})
    assert response.status_code == 200 and response.json()['changed'] == 1
    rows = assignments(keywords)
    assert not any(row[1] == 'animals/cat' for row in rows)
    assert any(row[1] == 'zoo/cat' for row in rows)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute(f'SELECT COUNT(*) FROM photos WHERE path IN ({",".join("?" * len(keywords))})', keywords).fetchone()[0] == 4


def test_rename_failure_rolls_back_all_earlier_assignment_changes(edition_client, keywords):
    captured = edition_client.post(ROOT + '/manage/preview', json={'source': 'source', 'target': 'new'}).json()
    before = assignments(keywords)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('CREATE TRIGGER fail_keyword_change BEFORE UPDATE ON photo_manual_tags '
                     'WHEN OLD.photo_path LIKE \'%/public/1.jpg\' BEGIN SELECT RAISE(ABORT, \'fixture\'); END')
    try:
        response = edition_client.post(ROOT + '/manage/apply', json={
            'source': 'source', 'target': 'new', 'preview_token': captured['preview_token']})
        assert response.status_code == 503
        assert assignments(keywords) == before
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DROP TRIGGER fail_keyword_change')
