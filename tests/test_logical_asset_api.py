"""Actual HTTP review/apply with disposable files and catalog rows."""
import base64
import json
from pathlib import Path
import sqlite3

import pytest

from db import DEFAULT_DB_PATH


@pytest.fixture
def bundle(tmp_path, seed_photos_prefix, monkeypatch):
    from api import config

    jpg, raw = tmp_path / 'capture.jpg', tmp_path / 'capture.CR2'
    jpg.write_bytes(b'JPEG fixture')
    raw.write_bytes(b'RAW fixture')
    monkeypatch.setitem(config.VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    seed_photos_prefix(str(tmp_path), [
        {'path': str(jpg), 'filename': jpg.name, 'star_rating': 5, 'is_kept': 1},
        {'path': str(raw), 'filename': raw.name, 'star_rating': 2, 'is_rejected': 1},
    ])
    yield {'operation': 'create', 'paths': [str(jpg), str(raw)], 'primary_path': str(jpg)}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM logical_assets WHERE id IN (SELECT asset_id FROM logical_asset_members WHERE photo_path LIKE ?)',
                     (str(tmp_path) + '%',))


def draft(client, change):
    response = client.post('/api/logical_assets/preview', json=change)
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, change, preview, **extra):
    return client.post('/api/logical_assets/apply', json={
        'change': change, 'preview_token': preview['preview_token'], **extra})


def test_create_primary_and_dissolve_preserve_file_and_review_values(edition_client, bundle):
    preview = draft(edition_client, bundle)
    assert set(preview['review_conflicts']) == {'star_rating', 'is_kept', 'is_rejected'}
    assert preview['preserves_file_metadata'] is True
    encoded = preview['preview_token'].split('.')[0]
    claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    assert str(Path(bundle['paths'][0]).parent) not in str(claims)
    assert submit(edition_client, bundle, preview).status_code == 409
    response = submit(edition_client, bundle, preview, acknowledge_review_conflicts=True)
    assert response.status_code == 200, response.text
    key = response.json()['asset_id']
    assert submit(edition_client, bundle, preview, acknowledge_review_conflicts=True).status_code == 409
    primary = {'operation': 'primary', 'asset_id': key, 'revision': 1, 'primary_path': bundle['paths'][1]}
    next_preview = draft(edition_client, primary)
    assert submit(edition_client, primary, next_preview, acknowledge_review_conflicts=True).json()['revision'] == 2
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?',
                            (bundle['paths'][0],)).fetchone() == (5, 1, 0)
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?',
                            (bundle['paths'][1],)).fetchone() == (2, 0, 1)
    dissolve = {'operation': 'dissolve', 'asset_id': key, 'revision': 2}
    response = submit(edition_client, dissolve, draft(edition_client, dissolve), acknowledge_review_conflicts=True)
    assert response.status_code == 200 and response.json()['dissolved'] is True
    assert Path(bundle['paths'][0]).read_bytes() == b'JPEG fixture'
    assert Path(bundle['paths'][1]).read_bytes() == b'RAW fixture'


@pytest.mark.parametrize('changed', ['file', 'review', 'permission', 'request', 'secret'])
def test_changed_preview_refuses_without_partial_membership(edition_client, bundle, monkeypatch, changed):
    from api import config, logical_asset_changes

    preview = draft(edition_client, bundle)
    if changed == 'file':
        Path(bundle['paths'][1]).write_bytes(b'changed RAW fixture')
    elif changed == 'review':
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('UPDATE photos SET star_rating=4 WHERE path=?', (bundle['paths'][1],))
    elif changed == 'permission':
        monkeypatch.setattr(logical_asset_changes, 'get_visibility_clause', lambda user: ('photos.path != ?', [bundle['paths'][1]]))
    elif changed == 'request':
        bundle = {**bundle, 'primary_path': bundle['paths'][1]}
    else:
        monkeypatch.setattr(config, 'JWT_SECRET', 'rotated-secret')
    response = submit(edition_client, bundle, preview, acknowledge_review_conflicts=True)
    assert response.status_code in (404, 409)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM logical_asset_members WHERE photo_path IN (?,?)', bundle['paths']).fetchone()[0] == 0


def test_read_only_preview_is_available_but_apply_is_edition_only(regular_client, edition_client, bundle):
    preview = draft(regular_client, bundle)
    assert submit(regular_client, bundle, preview, acknowledge_review_conflicts=True).status_code == 403
    assert draft(edition_client, bundle)['members'][0]['path'] in bundle['paths']


def test_unrelated_or_duplicate_physical_files_are_not_grouped(edition_client, bundle, seed_photos_prefix):
    other = Path(bundle['paths'][1]).with_name('different.CR2')
    other.write_bytes(b'unrelated RAW')
    seed_photos_prefix(str(other.parent), [{'path': str(other), 'filename': other.name}])
    response = edition_client.post('/api/logical_assets/preview', json={**bundle, 'paths': [bundle['paths'][0], str(other)]})
    assert response.status_code == 409


def test_preview_is_bound_to_its_owner(regular_client, edition_client, bundle):
    preview = draft(regular_client, bundle)
    assert submit(edition_client, bundle, preview, acknowledge_review_conflicts=True).status_code == 409


def test_expired_or_tampered_token_refuses_before_any_group_write(edition_client, bundle, monkeypatch):
    from api import logical_asset_changes

    preview = draft(edition_client, bundle)
    invalid = {**preview, 'preview_token': preview['preview_token'] + '0'}
    assert submit(edition_client, bundle, invalid, acknowledge_review_conflicts=True).status_code == 409
    monkeypatch.setattr(logical_asset_changes.time, 'time', lambda: preview['expires_at'] + 1)
    assert submit(edition_client, bundle, preview, acknowledge_review_conflicts=True).status_code == 409


def test_dissolve_is_available_offline_after_explicit_review(edition_client, bundle):
    result = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()
    Path(bundle['paths'][0]).unlink()
    change = {'operation': 'dissolve', 'asset_id': result['asset_id'], 'revision': 1}
    response = submit(edition_client, change, draft(edition_client, change), acknowledge_review_conflicts=True)
    assert response.status_code == 200
    assert response.json()['dissolved'] is True


def test_symlink_candidate_does_not_establish_a_group(edition_client, bundle, tmp_path):
    from tests.conftest import symlink_or_skip

    raw = Path(bundle['paths'][1])
    raw.unlink()
    target = tmp_path / 'different.bin'
    target.write_bytes(b'foreign RAW fixture')
    symlink_or_skip(raw, target)
    response = edition_client.post('/api/logical_assets/preview', json=bundle)
    assert response.status_code == 409
    assert str(target) not in response.text


def test_hidden_group_never_discloses_its_existence_or_revision(edition_client, bundle, monkeypatch):
    from api import logical_asset_changes

    created = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()
    monkeypatch.setattr(logical_asset_changes, 'get_visibility_clause',
                        lambda user: ('photos.path != ?', [bundle['paths'][1]]))
    for revision in (1, 2, 100):
        response = edition_client.post('/api/logical_assets/preview', json={
            'operation': 'primary', 'asset_id': created['asset_id'], 'revision': revision,
            'primary_path': bundle['paths'][0]})
        assert response.status_code == 404
        assert response.json() == {'detail': 'Logical photo unavailable'}


def test_concurrent_apply_accepts_only_one_group(edition_client, bundle):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    preview = draft(edition_client, bundle)
    ready = Barrier(2)

    def apply_once():
        ready.wait(timeout=5)
        return submit(edition_client, bundle, preview, acknowledge_review_conflicts=True).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: apply_once(), range(2)))
    assert sorted(statuses) == [200, 409]
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(DISTINCT asset_id) FROM logical_asset_members WHERE photo_path IN (?,?)',
                            bundle['paths']).fetchone()[0] == 1


def test_storage_failure_rolls_back_the_entire_apply(edition_client, bundle):
    preview = draft(edition_client, bundle)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("CREATE TRIGGER fail_logical_apply BEFORE INSERT ON logical_asset_members "
                     "WHEN NEW.position=1 BEGIN SELECT RAISE(ABORT,'injected'); END")
    try:
        response = submit(edition_client, bundle, preview, acknowledge_review_conflicts=True)
        assert response.status_code == 503
        assert 'injected' not in response.text
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            assert conn.execute('SELECT COUNT(*) FROM logical_asset_members WHERE photo_path IN (?,?)', bundle['paths']).fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM logical_assets WHERE primary_path IN (?,?)', bundle['paths']).fetchone()[0] == 0
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DROP TRIGGER fail_logical_apply')


def test_context_discovers_only_visible_indexed_candidates(edition_client, bundle, monkeypatch):
    from api import related_files, logical_asset_changes

    response = edition_client.get('/api/logical_assets/by-photo', params={'path': bundle['paths'][0]})
    assert response.status_code == 200
    body = response.json()
    assert body['can_group'] is True
    assert {item['path'] for item in body['candidates']} == set(bundle['paths'])
    def visibility(user):
        return 'photos.path != ?', [bundle['paths'][1]]
    monkeypatch.setattr(logical_asset_changes, 'get_visibility_clause', visibility)
    monkeypatch.setattr(related_files, 'get_visibility_clause', visibility)
    response = edition_client.get('/api/logical_assets/by-photo', params={'path': bundle['paths'][0]})
    assert response.status_code == 200
    assert response.json()['can_group'] is False
    assert bundle['paths'][1] not in response.text


def test_hidden_group_context_does_not_expose_any_membership(edition_client, bundle, monkeypatch):
    from api import logical_asset_changes

    created = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()
    response = edition_client.get('/api/logical_assets/by-photo', params={'path': bundle['paths'][0]})
    assert response.json()['asset']['asset_id'] == created['asset_id']
    monkeypatch.setattr(logical_asset_changes, 'get_visibility_clause',
                        lambda user: ('photos.path != ?', [bundle['paths'][1]]))
    response = edition_client.get('/api/logical_assets/by-photo', params={'path': bundle['paths'][0]})
    assert response.status_code == 200
    assert response.json() == {'asset': None, 'candidates': [], 'can_group': False}


def test_context_omits_ambiguous_indexed_aliases(edition_client, bundle, seed_photos_prefix, monkeypatch):
    from api import config

    root = str(Path(bundle['paths'][0]).parent)
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {'/raw-alias': root})
    seed_photos_prefix('/raw-alias/', [{'path': '/raw-alias/capture.CR2', 'filename': 'capture.CR2'}])
    response = edition_client.get('/api/logical_assets/by-photo', params={'path': bundle['paths'][0]})
    assert response.status_code == 200
    assert response.json()['can_group'] is False
    assert response.json()['candidates'] == [{'path': bundle['paths'][0], 'name': 'capture.jpg', 'kind': 'jpeg'}]


def test_assigned_alias_does_not_make_an_unassigned_alias_unique(edition_client, bundle, seed_photos_prefix, monkeypatch):
    from api import config
    from db import logical_assets

    root = str(Path(bundle['paths'][0]).parent)
    other = str(Path(root) / 'previously-renamed.jpg')
    seed_photos_prefix(root, [{'path': other, 'filename': 'previously-renamed.jpg'}])
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('BEGIN')
        logical_assets.create(conn, [other, bundle['paths'][1]], other, visibility_sql='1=1')
    monkeypatch.setitem(config.VIEWER_CONFIG, 'path_mapping', {'/raw-alias': root})
    seed_photos_prefix('/raw-alias/', [{'path': '/raw-alias/capture.CR2', 'filename': 'capture.CR2'}])
    response = edition_client.get('/api/logical_assets/by-photo', params={'path': bundle['paths'][0]})
    assert response.status_code == 200
    assert response.json()['can_group'] is False
    assert [candidate['path'] for candidate in response.json()['candidates']] == [bundle['paths'][0]]
    change = {**bundle, 'paths': [bundle['paths'][0], '/raw-alias/capture.CR2']}
    assert edition_client.post('/api/logical_assets/preview', json=change).status_code == 409


def test_single_surviving_representation_keeps_identity_and_can_choose_a_primary(edition_client, bundle):
    created = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('DELETE FROM photos WHERE path=?', (bundle['paths'][0],))
    state = edition_client.get('/api/logical_assets/by-photo', params={'path': bundle['paths'][1]}).json()['asset']
    assert state['asset_id'] == created['asset_id']
    assert state['primary_path'] is None and state['revision'] == 2
    assert [member['path'] for member in state['members']] == [bundle['paths'][1]]
    change = {'operation': 'primary', 'asset_id': created['asset_id'], 'revision': 2, 'primary_path': bundle['paths'][1]}
    response = submit(edition_client, change, draft(edition_client, change))
    assert response.status_code == 200 and response.json()['revision'] == 3


@pytest.mark.parametrize('operation', ['primary', 'dissolve'])
@pytest.mark.parametrize('mutation', ['edit', 'reset'])
def test_logical_review_change_invalidates_group_preview(edition_client, bundle, operation, mutation):
    created = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()
    key = created['asset_id']
    change = {'operation': operation, 'asset_id': key, 'revision': 1}
    if operation == 'primary':
        change['primary_path'] = bundle['paths'][1]
    preview = draft(edition_client, change)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        if mutation == 'edit':
            conn.execute("INSERT INTO logical_review_fields VALUES (?, 'another-owner', 'star_rating', 4, 'user')", (key,))
        else:
            # A reset with no surviving override still changes review authority.
            conn.execute("INSERT INTO logical_review_field_versions VALUES (?, 'another-owner', 'star_rating', 1)", (key,))
            conn.execute("INSERT INTO logical_review_versions VALUES (?, 'another-owner', 1)", (key,))
    response = submit(edition_client, change, preview, acknowledge_review_conflicts=True)
    assert response.status_code == 409, response.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT primary_path,revision FROM logical_assets WHERE id=?', (key,)).fetchone() == (bundle['primary_path'], 1)
        assert conn.execute('SELECT COUNT(*) FROM logical_asset_members WHERE asset_id=?', (key,)).fetchone()[0] == 2
    fresh = draft(edition_client, change)
    assert 'another-owner' not in json.dumps(fresh)
    assert submit(edition_client, change, fresh, acknowledge_review_conflicts=True).status_code == 200


def test_logical_review_http_edit_reset_and_stale_refusal(edition_client, bundle, monkeypatch):
    from api import config
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    assert state['values']['star_rating'] == 5
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    response = edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 3, 'is_kept': 0, 'is_rejected': 1}})
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed['values']['star_rating'] == 3 and changed['values']['is_rejected'] == 1
    assert changed['origins']['star_rating'] == 'user'
    assert edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 1}}).status_code == 409
    reset = {field: changed[field] for field in body}
    response = edition_client.post('/api/logical_assets/review', json={**reset, 'reset': ['star_rating', 'is_kept', 'is_rejected']})
    assert response.status_code == 200, response.text
    assert response.json()['values']['star_rating'] == 5
    assert response.json()['values']['is_kept'] == 1
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?', (bundle['primary_path'],)).fetchone() == (5, 1, 0)


def test_logical_review_partial_visibility_refuses_reads_and_writes(edition_client, bundle, monkeypatch):
    from api import config, logical_reviews
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    monkeypatch.setattr(logical_reviews, 'get_visibility_clause', lambda user: ('photos.path != ?', [bundle['paths'][1]]))
    assert edition_client.get('/api/logical_assets/review', params={'asset_id': key}).status_code == 404
    assert edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 1}}).status_code == 404
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT COUNT(*) FROM logical_review_fields WHERE asset_id=?', (key,)).fetchone()[0] == 0


def test_logical_review_read_only_and_changed_file_inputs(edition_client, regular_client, bundle, monkeypatch):
    from api import config
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = regular_client.get('/api/logical_assets/review', params={'asset_id': key})
    assert state.status_code == 200
    body = {field: state.json()[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    assert regular_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 1}}).status_code == 403
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute('UPDATE photos SET star_rating=4 WHERE path=?', (bundle['primary_path'],))
    assert edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 1}}).status_code == 409
    fresh = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    assert fresh['values']['star_rating'] == 4
    assert fresh['revision'] == 0


def test_logical_review_multi_user_authority_is_isolated(edition_client, regular_client, bundle, monkeypatch):
    from api import config
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': [str(Path(bundle['primary_path']).parent)]},
        'u1': {'directories': [str(Path(bundle['primary_path']).parent)]},
    })
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = regular_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    response = regular_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 4}})
    assert response.status_code == 200, response.text
    own = response.json()
    other = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    assert own['values']['star_rating'] == 4 and own['revision'] > 0
    assert other['values']['star_rating'] == 0 and other['revision'] == 0
    # A token from another account cannot be used with matching revision numbers.
    foreign = {field: other[field] for field in body}
    assert regular_client.post('/api/logical_assets/review', json={**foreign, 'patch': {'star_rating': 1}}).status_code == 409
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT owner,value FROM logical_review_fields WHERE asset_id=?', (key,)).fetchall() == [('u1', 4)]
        assert conn.execute('SELECT COUNT(*) FROM user_preferences WHERE photo_path IN (?,?)', bundle['paths']).fetchone()[0] == 0


def test_logical_review_storage_failure_rolls_back_all_fields(edition_client, bundle, monkeypatch):
    from api import config
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("CREATE TRIGGER fail_logical_review BEFORE INSERT ON logical_review_fields "
                     "WHEN NEW.field='decision' BEGIN SELECT RAISE(ABORT,'private injected failure'); END")
    try:
        response = edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 3, 'is_kept': 1, 'is_rejected': 0}})
        assert response.status_code == 503
        assert 'private injected' not in response.text
        fresh = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
        assert fresh == state
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            assert conn.execute('SELECT COUNT(*) FROM logical_review_fields WHERE asset_id=?', (key,)).fetchone()[0] == 0
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DROP TRIGGER fail_logical_review')


@pytest.mark.parametrize('patch', [
    {'star_rating': 6}, {'star_rating': True}, {'is_favorite': 2},
    {'is_kept': 1}, {'is_kept': 1, 'is_rejected': 1}, {'is_favorite': None},
])
def test_logical_review_invalid_values_leave_authority_unchanged(edition_client, bundle, monkeypatch, patch):
    from api import config
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    response = edition_client.post('/api/logical_assets/review', json={**body, 'patch': patch})
    assert response.status_code in (409, 422), response.text
    assert edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json() == state


def test_photo_response_carries_same_logical_snapshot_and_share_omits_it(edition_client, bundle, monkeypatch):
    from api import config, logical_reviews
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    changed = edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 3}}).json()
    for path in bundle['paths']:
        response = edition_client.get('/api/photo', params={'path': path})
        assert response.status_code == 200, response.text
        assert response.json()['logical_review'] == changed
    shared = edition_client.get('/api/photo', params={'path': bundle['primary_path'], 'token': 'advisory-share'})
    assert shared.status_code == 200
    assert 'logical_review' not in shared.json()
    monkeypatch.setattr(logical_reviews, 'get_visibility_clause', lambda user: ('photos.path != ?', [bundle['paths'][1]]))
    hidden = edition_client.get('/api/photo', params={'path': bundle['primary_path']})
    assert hidden.status_code == 200
    assert 'logical_review' not in hidden.json()
    targeted = edition_client.post('/api/photos/by_paths', json={'paths': [bundle['primary_path']], 'filters': {'type': '', 'hide_rejected': False}})
    assert targeted.status_code == 200, targeted.text
    assert len(targeted.json()['photos']) == 1
    assert 'logical_review' not in targeted.json()['photos'][0]


def test_gallery_and_targeted_rows_carry_logical_snapshot(edition_client, bundle):
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    filters = {'type': '', 'hide_blinks': False, 'hide_bursts': False, 'hide_duplicates': False,
               'hide_brackets': False, 'hide_panoramas': False, 'hide_rejected': False}
    targeted = edition_client.post('/api/photos/by_paths', json={'paths': bundle['paths'], 'filters': filters})
    assert targeted.status_code == 200, targeted.text
    assert len(targeted.json()['photos']) == 2
    assert all(photo['logical_review'] == state for photo in targeted.json()['photos'])
    listing = edition_client.get('/api/photos', params={**filters, 'per_page': 100})
    assert listing.status_code == 200, listing.text
    found = [photo for photo in listing.json()['photos'] if photo['path'] in bundle['paths']]
    assert len(found) == 1
    assert all(photo['logical_review'] == state for photo in found)


def test_opt_in_logical_gallery_scope_matches_sync_async_without_changing_physical_scope(edition_client, bundle):
    import asyncio
    from api.database import get_db, get_async_db
    from api.routers.gallery import gallery_scope_sql, gallery_scope_sql_async

    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    primary = {'operation': 'primary', 'asset_id': key, 'revision': 1, 'primary_path': bundle['paths'][1]}
    assert submit(edition_client, primary, draft(edition_client, primary), acknowledge_review_conflicts=True).status_code == 200
    filters = {'type': '', 'hide_blinks': False, 'hide_bursts': False, 'hide_duplicates': False,
               'hide_brackets': False, 'hide_panoramas': False, 'hide_rejected': False,
               'path_prefix': str(Path(bundle['primary_path']).parent), 'min_rating': 4}
    filters = {key: str(value).lower() for key, value in filters.items()}
    with get_db() as conn:
        conn.execute('BEGIN')
        physical, where, params = gallery_scope_sql(conn, filters, 'test')
        assert [row[0] for row in conn.execute(f'SELECT photos.path FROM {physical}{where}', params)] == [bundle['paths'][0]]
        projected, where, params = gallery_scope_sql(conn, filters, 'test', logical=True)
        expected = [tuple(row) for row in conn.execute(f'SELECT photos.path,photos.star_rating FROM {projected}{where}', params)]
        assert expected == [(bundle['paths'][1], 5)]
        for path in bundle['paths']:
            projected, where, params = gallery_scope_sql(conn, filters, 'test', exclude=[path], logical=True)
            assert conn.execute(f'SELECT COUNT(*) FROM {projected}{where}', params).fetchone()[0] == 0

    async def read_async():
        async with get_async_db() as conn:
            await conn.execute('BEGIN')
            projected, where, params = await gallery_scope_sql_async(conn, filters, 'test', logical=True)
            cursor = await conn.execute(f'SELECT photos.path,photos.star_rating FROM {projected}{where}', params)
            try:
                return [tuple(row) for row in await cursor.fetchall()]
            finally:
                await cursor.close()
    assert asyncio.run(read_async()) == expected


def test_logical_count_cache_hits_and_invalidates_after_shared_review_edit(edition_client, bundle, monkeypatch):
    import asyncio
    from api import config, db_helpers
    from api.database import get_async_db
    from api.routers.gallery import gallery_scope_sql_async

    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    filters = {'type': '', 'hide_blinks': 'false', 'hide_bursts': 'false', 'hide_duplicates': 'false',
               'hide_brackets': 'false', 'hide_panoramas': 'false', 'hide_rejected': 'false',
               'path_prefix': str(Path(bundle['primary_path']).parent), 'min_rating': '4'}
    hits = []
    lookup = db_helpers._count_cache_lookup
    def record_lookup(cache_key):
        result = lookup(cache_key)
        hits.append(result is not None)
        return result
    monkeypatch.setattr(db_helpers, '_count_cache_lookup', record_lookup)

    async def count():
        token = await db_helpers.snapshot_count_token()
        async with get_async_db() as conn:
            await conn.execute('BEGIN')
            source, where, params = await gallery_scope_sql_async(conn, filters, 'test', logical=True)
            return await db_helpers.get_cached_count_async(conn, where, params, source, token=token)
    assert asyncio.run(count()) == 1
    assert asyncio.run(count()) == 1
    assert hits[-1] is True
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    response = edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 2}})
    assert response.status_code == 200, response.text
    assert asyncio.run(count()) == 0
    assert hits[-1] is False
    assert asyncio.run(count()) == 0
    assert hits[-1] is True


def test_logical_read_endpoints_agree_on_primary_shared_rating_and_count(edition_client, bundle):
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    primary = {'operation': 'primary', 'asset_id': key, 'revision': 1, 'primary_path': bundle['paths'][1]}
    assert submit(edition_client, primary, draft(edition_client, primary), acknowledge_review_conflicts=True).status_code == 200
    filters = {'type': '', 'hide_blinks': 'false', 'hide_bursts': 'false', 'hide_duplicates': 'false',
               'hide_brackets': 'false', 'hide_panoramas': 'false', 'hide_rejected': 'false',
               'path_prefix': str(Path(bundle['primary_path']).parent), 'min_rating': '4'}
    listing = edition_client.get('/api/photos', params=filters)
    assert listing.status_code == 200, listing.text
    page = listing.json()
    assert page['total'] == page['photo_total'] == 1
    assert [(photo['path'], photo['star_rating']) for photo in page['photos']] == [(bundle['paths'][1], 5)]
    count = edition_client.get('/api/photos/count', params=filters)
    paths = edition_client.get('/api/photos/paths', params=filters)
    assert count.status_code == paths.status_code == 200
    assert count.json()['total'] == paths.json()['total'] == 1
    assert paths.json()['paths'] == [bundle['paths'][1]]
    repair = edition_client.post('/api/photos/by_paths', json={'paths': bundle['paths'], 'filters': filters})
    assert repair.status_code == 200, repair.text
    assert repair.json()['missing'] == []
    assert [(photo['path'], photo['star_rating']) for photo in repair.json()['photos']] == [(path, 5) for path in bundle['paths']]


def test_semantic_companion_hits_resolve_one_primary_across_read_endpoints(edition_client, bundle, monkeypatch):
    from api import config
    from api.routers import gallery
    from api.routers.search import Candidates

    monkeypatch.setitem(config.VIEWER_CONFIG['features'], 'show_semantic_search', True)
    submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True)
    # Only the non-primary RAW passes the semantic threshold.
    candidates = Candidates({bundle['paths'][1]: 0.9}, {bundle['paths'][1]: 0.9}, json.dumps([bundle['paths'][1]]))
    async def semantic(*args):
        return candidates
    monkeypatch.setattr(gallery, 'semantic_candidates', semantic)
    params = {'type': '', 'hide_blinks': 'false', 'hide_bursts': 'false', 'hide_duplicates': 'false',
              'hide_brackets': 'false', 'hide_panoramas': 'false', 'hide_rejected': 'false',
              'path_prefix': str(Path(bundle['primary_path']).parent), 'semantic_q': 'test capture', 'sort': 'relevance'}
    response = edition_client.get('/api/photos', params=params)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page['total'] == 1
    assert [photo['path'] for photo in page['photos']] == [bundle['primary_path']]
    assert page['photos'][0]['similarity'] == 0.9
    for route in ('/api/photos/count', '/api/photos/paths'):
        result = edition_client.get(route, params=params)
        assert result.status_code == 200, result.text
        assert result.json()['total'] == 1
    assert candidates.blended == {bundle['paths'][1]: 0.9}
    assert candidates._ordered_json == {}


def test_http_manual_stack_counts_logical_pair_once(edition_client, bundle, seed_photos_prefix):
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    primary = {'operation': 'primary', 'asset_id': key, 'revision': 1, 'primary_path': bundle['paths'][1]}
    assert submit(edition_client, primary, draft(edition_client, primary), acknowledge_review_conflicts=True).status_code == 200
    other = str(Path(bundle['primary_path']).with_name('other.jpg'))
    seed_photos_prefix(str(Path(other).parent), [{'path': other, 'filename': 'other.jpg', 'aggregate': 5.0}])
    stack = edition_client.post('/api/stacks', json={'paths': [*bundle['paths'], other], 'cover_path': bundle['primary_path']})
    assert stack.status_code == 201, stack.text
    filters = {'type': '', 'hide_blinks': 'false', 'hide_bursts': 'false', 'hide_duplicates': 'false',
               'hide_brackets': 'false', 'hide_panoramas': 'false', 'hide_rejected': 'false',
               'path_prefix': str(Path(other).parent)}
    response = edition_client.get('/api/photos', params=filters)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page['total'] == 1 and page['photo_total'] == 2
    assert page['photos'][0]['path'] == bundle['paths'][1]
    assert page['photos'][0]['stack_count'] == page['photos'][0]['stack_total_count'] == 2
    count = edition_client.get('/api/photos/count', params=filters)
    assert count.status_code == 200 and count.json()['total'] == 2


@pytest.mark.parametrize('route,extra,field,value', [
    ('batch_rating', {'rating': 4}, 'star_rating', 4),
    ('batch_favorite', {}, 'is_favorite', 1),
    ('batch_reject', {}, 'is_rejected', 1),
    ('batch_review', {'decision': 'undecided'}, 'is_kept', 0),
])
def test_logical_batch_writes_once_without_changing_original_files(edition_client, bundle, route, extra, field, value):
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    response = edition_client.post('/api/photos/' + route, json={'photo_paths': bundle['paths'], **extra})
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 1 and response.json()['logical_asset_ids'] == [key]
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    assert state['values'][field] == value
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?', (bundle['paths'][0],)).fetchone() == (5, 1, 0)
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?', (bundle['paths'][1],)).fetchone() == (2, 0, 1)


def test_filter_scoped_batch_uses_logical_review_filter_and_alias_exclusion(edition_client, bundle):
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    filters = {'type': '', 'hide_blinks': 'false', 'hide_bursts': 'false', 'hide_duplicates': 'false',
               'hide_brackets': 'false', 'hide_panoramas': 'false', 'hide_rejected': 'false',
               'path_prefix': str(Path(bundle['primary_path']).parent), 'min_rating': '4'}
    excluded = edition_client.post('/api/photos/batch_rating', json={'filters': filters, 'exclude': [bundle['paths'][1]], 'rating': 1})
    assert excluded.status_code == 200 and excluded.json()['count'] == 0
    response = edition_client.post('/api/photos/batch_rating', json={'filters': filters, 'rating': 1})
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 1
    # Physical JPEG still has five stars, but logical min-rating no longer matches.
    again = edition_client.post('/api/photos/batch_rating', json={'filters': filters, 'rating': 4})
    assert again.status_code == 200 and again.json()['count'] == 0
    assert edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()['values']['star_rating'] == 1


def test_mixed_batch_failure_rolls_back_logical_and_physical_reviews(edition_client, bundle, seed_photos_prefix):
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    other = str(Path(bundle['primary_path']).with_name('other.jpg'))
    seed_photos_prefix(str(Path(other).parent), [{'path': other, 'filename': 'other.jpg', 'star_rating': 2}])
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("CREATE TRIGGER fail_mixed_review BEFORE UPDATE OF star_rating ON photos "
                     "BEGIN SELECT RAISE(ABORT,'injected physical failure'); END")
    try:
        response = edition_client.post('/api/photos/batch_rating', json={'photo_paths': [bundle['primary_path'], other], 'rating': 4})
        assert response.status_code == 500
        assert 'injected' not in response.text
        assert edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json() == state
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (other,)).fetchone()[0] == 2
            assert conn.execute('SELECT COUNT(*) FROM logical_review_fields WHERE asset_id=?', (key,)).fetchone()[0] == 0
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DROP TRIGGER fail_mixed_review')


@pytest.mark.parametrize('filtered', [False, True])
def test_batch_hidden_companion_never_falls_back_to_physical_write(edition_client, bundle, monkeypatch, filtered):
    from api import logical_batch
    from api.routers import gallery

    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    def visibility(user):
        return 'photos.path != ?', [bundle['paths'][1]]
    monkeypatch.setattr(logical_batch, 'get_visibility_clause', visibility)
    monkeypatch.setattr(gallery, 'get_visibility_clause', visibility)
    body = {'rating': 1, 'photo_paths': [bundle['primary_path']]}
    if filtered:
        body = {'rating': 1, 'filters': {'type': '', 'hide_blinks': 'false', 'hide_bursts': 'false',
                'hide_duplicates': 'false', 'hide_brackets': 'false', 'hide_panoramas': 'false', 'hide_rejected': 'false',
                'path_prefix': str(Path(bundle['primary_path']).parent)}}
    response = edition_client.post('/api/photos/batch_rating', json=body)
    assert response.status_code == 404, response.text
    assert bundle['paths'][1] not in response.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (bundle['primary_path'],)).fetchone()[0] == 5
        assert conn.execute('SELECT COUNT(*) FROM logical_review_fields WHERE asset_id=?', (key,)).fetchone()[0] == 0


def test_mixed_batch_success_counts_logical_and_independent_photos(edition_client, bundle, seed_photos_prefix):
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    other = str(Path(bundle['primary_path']).with_name('other.jpg'))
    seed_photos_prefix(str(Path(other).parent), [{'path': other, 'filename': 'other.jpg', 'star_rating': 2}])
    response = edition_client.post('/api/photos/batch_rating', json={'photo_paths': [*bundle['paths'], other], 'rating': 4})
    assert response.status_code == 200, response.text
    assert response.json()['count'] == 2 and response.json()['logical_asset_ids'] == [key]
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (other,)).fetchone()[0] == 4
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (bundle['primary_path'],)).fetchone()[0] == 5


def test_direct_review_apis_update_one_logical_authority_from_either_file(edition_client, bundle, monkeypatch):
    from api import config
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    rating = edition_client.post('/api/photo/set_rating', json={'photo_path': bundle['paths'][1], 'rating': 4})
    assert rating.status_code == 200 and rating.json()['rating'] == 4
    favorite = edition_client.post('/api/photo/toggle_favorite', json={'photo_path': bundle['paths'][0]})
    assert favorite.status_code == 200 and favorite.json()['is_favorite'] is True
    rejected = edition_client.post('/api/photo/toggle_rejected', json={'photo_path': bundle['paths'][1]})
    assert rejected.status_code == 200 and rejected.json()['is_rejected'] is True
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    assert state['values'] == {'star_rating': 0, 'is_favorite': 0, 'is_kept': 0, 'is_rejected': 1}
    # This time JPEG toggles the same decision off, rather than its original file flag.
    undone = edition_client.post('/api/photo/toggle_rejected', json={'photo_path': bundle['paths'][0]})
    assert undone.status_code == 200 and undone.json()['is_rejected'] is False
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?', (bundle['paths'][0],)).fetchone() == (5, 1, 0)
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?', (bundle['paths'][1],)).fetchone() == (2, 0, 1)


@pytest.mark.parametrize('route,extra', [('set_rating', {'rating': 4}), ('toggle_favorite', {}), ('toggle_rejected', {})])
def test_direct_review_hidden_companion_never_writes_original(edition_client, bundle, monkeypatch, route, extra):
    from api import config, logical_reviews
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    monkeypatch.setattr(logical_reviews, 'get_visibility_clause', lambda user: ('photos.path != ?', [bundle['paths'][1]]))
    response = edition_client.post('/api/photo/' + route, json={'photo_path': bundle['primary_path'], **extra})
    assert response.status_code == 404, response.text
    assert bundle['paths'][1] not in response.text
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating,is_kept,is_rejected FROM photos WHERE path=?', (bundle['primary_path'],)).fetchone() == (5, 1, 0)
        assert conn.execute('SELECT COUNT(*) FROM logical_review_fields WHERE asset_id=?', (key,)).fetchone()[0] == 0


def test_direct_agent_review_does_not_claim_unchanged_human_logical_value(edition_client, bundle, monkeypatch):
    from api import config
    from api.auth import CurrentUser, require_auth
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    response = edition_client.post('/api/photo/set_rating', json={'photo_path': bundle['primary_path'], 'rating': 4})
    assert response.status_code == 200
    agent = CurrentUser(user_id='test', edition_authenticated=True, agent=True)
    edition_client.app.dependency_overrides[require_auth] = lambda: agent
    try:
        response = edition_client.post('/api/photo/set_rating', json={'photo_path': bundle['paths'][1], 'rating': 4})
        assert response.status_code == 200
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            assert conn.execute('SELECT value,origin FROM logical_review_fields WHERE asset_id=? AND field=?', (key, 'star_rating')).fetchone() == (4, 'user')
        response = edition_client.post('/api/photo/set_rating', json={'photo_path': bundle['paths'][1], 'rating': 3})
        assert response.status_code == 200
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            assert conn.execute('SELECT value,origin FROM logical_review_fields WHERE asset_id=? AND field=?', (key, 'star_rating')).fetchone() == (3, 'agent')
    finally:
        edition_client.app.dependency_overrides.pop(require_auth, None)


def test_direct_favorite_storage_failure_rolls_back_logical_values_and_clock(edition_client, bundle, monkeypatch):
    from api import config
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    before = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        conn.execute("CREATE TRIGGER fail_direct_review BEFORE INSERT ON logical_review_fields "
                     "WHEN NEW.field='decision' BEGIN SELECT RAISE(ABORT,'private injected failure'); END")
    try:
        response = edition_client.post('/api/photo/toggle_favorite', json={'photo_path': bundle['paths'][1]})
        assert response.status_code == 500
        assert 'private injected' not in response.text
        assert edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json() == before
    finally:
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            conn.execute('DROP TRIGGER fail_direct_review')


def test_logical_history_http_capture_list_and_revert_never_exposes_internal_state(edition_client, bundle, monkeypatch):
    from api import config
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    key = submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True).json()['asset_id']
    state = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    body = {field: state[field] for field in ('asset_id', 'group_revision', 'revision', 'input_token')}
    assert edition_client.post('/api/logical_assets/review', json={**body, 'patch': {'star_rating': 4}}).status_code == 200
    response = edition_client.get('/api/organization_history')
    assert response.status_code == 200, response.text
    entry = next(entry for entry in response.json()['entries'] if entry['kind'] == 'logical_review' and entry['changes'][0]['path'] in bundle['paths'])
    change = entry['changes'][0]
    assert change['before'] == [5, 0, 0, 1] and change['after'] == [4, 0, 0, 1]
    assert set(change) == {'path', 'before', 'after', 'revision'}
    assert 'input_token' not in response.text and 'override_before' not in response.text
    restored = edition_client.post(f"/api/organization_history/{entry['id']}/revert")
    assert restored.status_code == 200 and restored.json()['changed'] == 1
    current = edition_client.get('/api/logical_assets/review', params={'asset_id': key}).json()
    assert current['values']['star_rating'] == 5 and current['origins']['star_rating'] == 'file'
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 409
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        assert conn.execute('SELECT star_rating FROM photos WHERE path=?', (bundle['primary_path'],)).fetchone()[0] == 5


def test_logical_history_hidden_companion_hides_and_refuses_receipt(edition_client, bundle, monkeypatch):
    from api import config, logical_reviews
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-only')
    submit(edition_client, bundle, draft(edition_client, bundle), acknowledge_review_conflicts=True)
    assert edition_client.post('/api/photo/set_rating', json={'photo_path': bundle['primary_path'], 'rating': 4}).status_code == 200
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        entry_id = conn.execute("SELECT MAX(id) FROM organization_history WHERE kind='logical_review'").fetchone()[0]
    monkeypatch.setattr(logical_reviews, 'get_visibility_clause', lambda user: ('photos.path != ?', [bundle['paths'][1]]))
    listed = edition_client.get('/api/organization_history')
    assert listed.status_code == 200
    assert entry_id not in {entry['id'] for entry in listed.json()['entries']}
    assert edition_client.post(f'/api/organization_history/{entry_id}/revert').status_code == 404
