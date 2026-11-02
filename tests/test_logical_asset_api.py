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
    assert len(found) == 2
    assert all(photo['logical_review'] == state for photo in found)
