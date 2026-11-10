"""Absent capture dates are exact predicates, shared by reads and captured writes."""

import json
import sqlite3

from api.routers.gallery import _build_gallery_where
from db import DEFAULT_DB_PATH
from tests.test_gallery_match_logic import _photo, library as library
from tests.test_person_match_groups import PREFIX, OWNER, group as group, owner_client as owner_client


def test_missing_capture_date_is_not_zero_malformed_or_a_scan_date(library):
    for name, date in [('null', None), ('empty', ''), ('blank', ' \t\r\n'),
                       ('zero', '0'), ('bad', 'not-a-date'), ('known', '2026:10:31 12:00:00')]:
        _photo(library, '/' + name, date_taken=date)
    def matching(**filters):
        clauses, args = _build_gallery_where(filters, library)
        return {r[0] for r in library.execute('SELECT path FROM photos WHERE ' + ' AND '.join(clauses or ['1=1']), args)}
    assert matching(no_capture_date='1') == {'/null', '/empty', '/blank'}
    assert matching(no_capture_date='true', date_from='2026-01-01') == set()
    assert len(matching(no_capture_date='0')) == 6


def test_missing_date_authorized_reads_saved_rules_and_excluded_write_agree(owner_client, group):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        for name in ['alice/one.jpg', 'alice/two.jpg', 'bob/foreign.jpg']:
            conn.execute('UPDATE photos SET date_taken=NULL WHERE path=?', (PREFIX + name,))
    filters = {'no_capture_date': '1', 'path_prefix': PREFIX, 'type': '', 'hide_bursts': '0'}
    expected = {PREFIX + 'alice/one.jpg', PREFIX + 'alice/two.jpg'}
    for endpoint, field in [('photos', 'photos'), ('photos/paths', 'paths')]:
        result = owner_client.get('/api/' + endpoint, params=filters)
        assert result.status_code == 200, result.text
        rows = result.json()[field]
        assert {r['path'] if isinstance(r, dict) else r for r in rows} == expected
    assert owner_client.get('/api/photos/count', params=filters).json()['total'] == 2
    rows = owner_client.post('/api/photos/by_paths', json={'paths': [r['path'] for r in group], 'filters': filters})
    assert rows.status_code == 200, rows.text
    assert {r['path'] for r in rows.json()['photos']} == expected
    created = owner_client.post('/api/albums', json={'name': 'missing-date', 'is_smart': True, 'smart_filter_json': json.dumps(filters)})
    assert created.status_code == 200, created.text
    album = created.json()['id']
    try:
        opened = owner_client.get(f'/api/albums/{album}/photos')
        assert opened.status_code == 200, opened.text
        assert {r['path'] for r in opened.json()['photos']} == expected
    finally:
        owner_client.delete(f'/api/albums/{album}')
    applied = owner_client.post('/api/photos/batch_rating', json={'filters': filters, 'exclude': [PREFIX + 'alice/one.jpg'], 'rating': 4})
    assert applied.status_code == 200, applied.text
    assert applied.json()['count'] == 1
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert dict(conn.execute('SELECT photo_path,star_rating FROM user_preferences WHERE user_id=? AND photo_path LIKE ?', (OWNER, PREFIX + '%'))) == {PREFIX + 'alice/two.jpg': 4}


def test_timeline_excludes_the_same_blank_capture_dates(owner_client, group):
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET date_taken=? WHERE path=?', (' \t\r\n', PREFIX + 'alice/one.jpg'))
        conn.execute('UPDATE photos SET date_taken=NULL WHERE path=?', (PREFIX + 'alice/two.jpg',))
    result = owner_client.get('/api/timeline/years', params={'hide_bursts': '0', 'hide_duplicates': '0'})
    assert result.status_code == 200, result.text
    assert [(row['year'], row['count']) for row in result.json()['years']] == [('2026', 2)]
