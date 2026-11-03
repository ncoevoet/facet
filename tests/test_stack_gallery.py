"""Manual stacks reduce cards without losing matching photos or action scope."""
import pytest

PREFIX = '/stack-gallery/'


@pytest.fixture
def stack_photos(seed_photos_prefix):
    rows = [
        {'path': PREFIX + 'cover.jpg', 'filename': 'cover.jpg', 'aggregate': 8.0,
         'date_taken': '2024:01:01 10:00:00', 'gps_latitude': 1., 'gps_longitude': 1.,
         'is_burst_lead': 1, 'burst_group_id': 321},
        {'path': PREFIX + 'other.jpg', 'filename': 'other.jpg', 'aggregate': 7.0,
         'date_taken': '2024:01:01 10:00:01', 'is_burst_lead': 0, 'burst_group_id': 321},
        {'path': PREFIX + 'third.jpg', 'filename': 'third.jpg', 'aggregate': 6.0,
         'date_taken': '2024:01:01 10:00:02', 'is_burst_lead': 0, 'burst_group_id': 321},
        {'path': PREFIX + 'single.jpg', 'filename': 'single.jpg', 'aggregate': 5.0,
         'date_taken': '2024:01:01 10:01:00'},
    ]
    seed_photos_prefix(PREFIX, rows)
    return [r['path'] for r in rows]


@pytest.fixture
def manual_stack(edition_client, stack_photos):
    r = edition_client.post('/api/stacks', json={
        'paths': stack_photos[:3], 'cover_path': stack_photos[0]})
    assert r.status_code == 201, r.text
    stack = r.json()['stack']
    yield stack


def listing(client, **params):
    r = client.get('/api/photos', params={'path_prefix': PREFIX, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_collapse_preserves_true_photo_count_and_whole_view_scope(edition_client, manual_stack):
    page = listing(edition_client)
    assert [p['path'] for p in page['photos']] == [PREFIX + 'cover.jpg', PREFIX + 'single.jpg']
    assert page['total'] == 2
    assert page['photo_total'] == 4
    assert page['photos'][0]['stack_count'] == 3
    assert page['photos'][0]['stack_total_count'] == 3
    for route in ('/api/photos/count', '/api/photos/paths'):
        r = edition_client.get(route, params={'path_prefix': PREFIX})
        assert r.status_code == 200, r.text
        assert r.json()['total'] == 4


def test_noncover_filter_match_is_discoverable_despite_automatic_burst_hide(edition_client, manual_stack):
    page = listing(edition_client, no_gps='1')
    assert [p['path'] for p in page['photos']] == [PREFIX + 'other.jpg', PREFIX + 'single.jpg']
    assert page['photo_total'] == 3
    assert page['photos'][0]['stack_count'] == 2
    assert page['photos'][0]['stack_total_count'] == 3


def test_expand_and_explicit_stack_browse(edition_client, manual_stack):
    expanded = listing(edition_client, collapse_stacks='0')
    assert expanded['total'] == expanded['photo_total'] == 4
    scoped = listing(edition_client, stack_id=manual_stack['id'])
    assert [p['path'] for p in scoped['photos']] == [PREFIX + x for x in ('cover.jpg', 'other.jpg', 'third.jpg')]
    assert scoped['total'] == 3


def test_representatives_are_paged_before_limit(edition_client, manual_stack):
    pages = [listing(edition_client, per_page='1', page=str(n)) for n in (1, 2, 3)]
    assert [p['path'] for page in pages for p in page['photos']] == [PREFIX + 'cover.jpg', PREFIX + 'single.jpg']
    assert [page['total_pages'] for page in pages] == [2, 2, 2]
    assert [page['has_more'] for page in pages] == [True, False, False]


def test_nonmember_does_not_get_stack_metadata(edition_client, manual_stack):
    page = listing(edition_client)
    single = next(p for p in page['photos'] if p['path'].endswith('single.jpg'))
    assert single.get('stack_id') is None


def test_unknown_stack_scope_is_not_broadened(edition_client, stack_photos):
    r = edition_client.get('/api/photos', params={'stack_id': '00000000-0000-0000-0000-000000000000'})
    assert r.status_code == 404


def test_invalid_collapse_flag_is_rejected(edition_client):
    assert edition_client.get('/api/photos', params={'collapse_stacks': 'sometimes'}).status_code == 422


def test_album_with_only_noncover_member_keeps_that_photo(edition_client, manual_stack):
    album = edition_client.post('/api/albums', json={'name': 'stack subset'}).json()
    try:
        r = edition_client.post(f"/api/albums/{album['id']}/photos", json={'photo_paths': [PREFIX + 'third.jpg']})
        assert r.status_code == 200, r.text
        page = listing(edition_client, album_id=str(album['id']))
        assert [p['path'] for p in page['photos']] == [PREFIX + 'third.jpg']
        assert page['photo_total'] == page['total'] == 1
        assert page['photos'][0]['stack_count'] == 1
        assert page['photos'][0]['stack_total_count'] == 3
    finally:
        edition_client.delete(f"/api/albums/{album['id']}")


def test_sort_uses_chosen_representative_without_changing_cover(edition_client, manual_stack):
    page = listing(edition_client, sort='date_taken', sort_direction='DESC')
    assert [p['path'] for p in page['photos']] == [PREFIX + 'single.jpg', PREFIX + 'cover.jpg']
    page = listing(edition_client, no_gps='1', sort='date_taken', sort_direction='DESC')
    # Stored order picks the first matching member, then global sort places it.
    assert [p['path'] for p in page['photos']] == [PREFIX + 'single.jpg', PREFIX + 'other.jpg']


def test_changing_cover_changes_representative_and_count_stays_correct(edition_client, manual_stack, stack_photos):
    r = edition_client.put('/api/stacks/' + manual_stack['id'], json={
        'paths': stack_photos[:3], 'cover_path': stack_photos[2],
        'expected_revision': manual_stack['revision']})
    assert r.status_code == 200, r.text
    page = listing(edition_client)
    assert {p['path'] for p in page['photos']} == {stack_photos[2], stack_photos[3]}
    assert page['photo_total'] == 4


def test_by_paths_exact_list_does_not_collapse(edition_client, manual_stack, stack_photos):
    r = edition_client.post('/api/photos/by_paths', json={'paths': stack_photos[:3]})
    assert r.status_code == 200, r.text
    assert [p['path'] for p in r.json()['photos']] == stack_photos[:3]


def test_other_owner_stacks_cannot_collapse_or_hide_count(edition_client, manual_stack, monkeypatch):
    from api import stack_gallery
    monkeypatch.setattr(stack_gallery, 'owner_for_user', lambda user_id: 'another-owner')
    page = listing(edition_client, hide_bursts='0', hide_duplicates='0')
    assert page['total'] == page['photo_total'] == 4
    assert all('stack_id' not in p for p in page['photos'])


def test_actual_account_visibility_filters_members_before_grouping(edition_client, regular_client, seed_photos_prefix, monkeypatch):
    from api import config
    paths = [PREFIX + 'private/cover.jpg', PREFIX + 'public/a.jpg', PREFIX + 'public/b.jpg']
    seed_photos_prefix(PREFIX, [dict(path=p, filename=p.rsplit('/', 1)[-1], aggregate=5.0) for p in paths])
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': [PREFIX]}, 'u1': {'directories': [PREFIX]}})
    r = edition_client.post('/api/stacks', json={'paths': paths, 'cover_path': paths[0]})
    assert r.status_code == 201, r.text
    stack = r.json()['stack']
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': [PREFIX + 'public/']}, 'u1': {'directories': [PREFIX]}})
    page = listing(edition_client)
    assert page['total'] == 1 and page['photo_total'] == 2
    item = page['photos'][0]
    assert item['path'] == paths[1]
    assert item['stack_count'] == item['stack_total_count'] == 2
    assert paths[0] not in str(page)
    assert edition_client.delete('/api/stacks/' + stack['id'], params={'expected_revision': stack['revision']}).status_code == 409
    # The other account sees all permitted photos, never this owner's grouping.
    other = listing(regular_client)
    assert all('stack_id' not in p for p in other['photos'])
    assert other['total'] == other['photo_total']


def test_stack_filter_composes_with_other_filters(edition_client, manual_stack):
    page = listing(edition_client, stack_id=manual_stack['id'], no_gps='1')
    assert {p['path'] for p in page['photos']} == {PREFIX + 'other.jpg', PREFIX + 'third.jpg'}
    assert page['total'] == page['photo_total'] == 2


def test_private_stack_filter_is_fail_closed_for_share_builders(edition_client, manual_stack):
    from api.database import get_db
    from api.routers.gallery import _build_gallery_where
    with get_db() as conn:
        clauses, values = _build_gallery_where({'stack_id': manual_stack['id']}, conn, include_manual=False)
        assert conn.execute('SELECT COUNT(*) FROM photos WHERE ' + ' AND '.join(clauses), values).fetchone()[0] == 0


def test_window_work_is_bounded_to_matching_stack_members(edition_client, manual_stack):
    from api.database import get_db
    from api.stack_gallery import projection
    with get_db() as conn:
        ranked = projection('photos', ' WHERE photos.path LIKE ?', [PREFIX + '%'], '')
        count = conn.execute(ranked.cte + ' SELECT COUNT(*) FROM stack_ranked', ranked.params).fetchone()[0]
        assert count == 3  # The standalone photo must not enter the window sort.


@pytest.mark.parametrize('include_victim_id', [False, True])
def test_smart_album_cannot_spoof_private_stack_owner(edition_client, regular_client, stack_photos, monkeypatch, include_victim_id):
    import json
    from api import config
    from api.database import get_db
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': [PREFIX]}, 'u1': {'directories': [PREFIX]}})
    r = edition_client.post('/api/stacks', json={'paths': stack_photos[:3], 'cover_path': stack_photos[0]})
    assert r.status_code == 201, r.text
    filters = {'path_prefix': PREFIX, 'hide_bursts': '1', '_manual_stack_owner': 'test'}
    if include_victim_id:
        filters['stack_id'] = r.json()['stack']['id']
    with get_db() as conn, conn:
        aid = conn.execute('INSERT INTO albums(name,user_id,is_smart,smart_filter_json) VALUES (?,?,1,?)',
                           ('owner spoof', 'u1', json.dumps(filters))).lastrowid
    try:
        response = regular_client.get(f'/api/albums/{aid}/photos')
        assert response.status_code == 200, response.text
        items = [p['path'] for p in response.json()['photos']]
        assert set(items) == (set() if include_victim_id else {stack_photos[0], stack_photos[3]})
    finally:
        with get_db() as conn, conn:
            conn.execute('DELETE FROM albums WHERE id=?', (aid,))


def test_own_stack_smart_album_agrees_between_sync_and_async(edition_client, manual_stack):
    import json
    from api.database import get_db
    from api.routers.albums import _resolve_album_member_paths
    with get_db() as conn, conn:
        aid = conn.execute('INSERT INTO albums(name,user_id,is_smart,smart_filter_json) VALUES (?,?,1,?)',
                           ('own stack', 'test', json.dumps({'stack_id': manual_stack['id']}))).lastrowid
        row = conn.execute('SELECT * FROM albums WHERE id=?', (aid,)).fetchone()
        expected = _resolve_album_member_paths(conn, row)
    try:
        response = edition_client.get(f'/api/albums/{aid}/photos')
        assert response.status_code == 200, response.text
        assert {p['path'] for p in response.json()['photos']} == set(expected)
        assert len(expected) == 3
    finally:
        with get_db() as conn, conn:
            conn.execute('DELETE FROM albums WHERE id=?', (aid,))


@pytest.mark.parametrize('scope', ['owner', 'other-owner', 'no-owner'])
def test_hidden_categories_exclude_only_own_restored_manual_members(
        edition_client, manual_stack, seed_photos_prefix, monkeypatch, scope):
    from api import stack_gallery
    from api.database import get_db
    seed_photos_prefix(PREFIX + 'hidden/', [
        {'path': PREFIX + 'hidden/blink.jpg', 'filename': 'blink.jpg', 'is_blink': 1},
        {'path': PREFIX + 'hidden/follower.jpg', 'filename': 'follower.jpg',
         'is_burst_lead': 0, 'burst_group_id': 321,
         'duplicate_group_id': 654, 'is_duplicate_lead': 0},
        {'path': PREFIX + 'hidden/bracket.jpg', 'filename': 'bracket.jpg',
         'sequence_kind': 'bracket', 'sequence_group_id': 700, 'sequence_ev_offset': -2.0},
        {'path': PREFIX + 'hidden/panorama.jpg', 'filename': 'panorama.jpg',
         'sequence_kind': 'panorama', 'sequence_group_id': 701, 'is_sequence_lead': 0},
    ])
    with get_db() as conn, conn:
        conn.execute('UPDATE photos SET duplicate_group_id=654, is_duplicate_lead=0 WHERE path IN (?,?)',
                     (PREFIX + 'other.jpg', PREFIX + 'third.jpg'))
    if scope != 'owner':
        monkeypatch.setattr(stack_gallery, 'owner_for_user',
                            lambda user_id: 'another-owner' if scope == 'other-owner' else None)
    page = listing(edition_client, hide_blinks='1', hide_bursts='1', hide_duplicates='1',
                   hide_brackets='1', hide_panoramas='1')
    hidden = page['hidden_summary']
    expected_followers = 1 if scope == 'owner' else 3
    assert hidden == {'total': expected_followers + 3, 'blinks': 1,
                      'bursts': expected_followers, 'duplicates': expected_followers,
                      'brackets': 1, 'panoramas': 1, 'rejected': 0}
    assert page['photo_total'] == (4 if scope == 'owner' else 2)
    # A filter on a noncover stack member counts only that authorized scope.
    subset = listing(edition_client, no_gps='1', hide_blinks='1', hide_bursts='1', hide_duplicates='1',
                   hide_brackets='1', hide_panoramas='1')
    assert subset['hidden_summary'] == hidden
    assert subset['photo_total'] == (3 if scope == 'owner' else 1)
