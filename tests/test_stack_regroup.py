"""Atomic explicit regrouping, bounded previews and whole-operation Undo."""
import contextlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.auth import CurrentUser
from db import organization_history as history, stacks
from db.schema import init_database


@pytest.fixture
def conn(tmp_path):
    filename = str(tmp_path / 'regroup.db')
    init_database(filename)
    with sqlite3.connect(filename) as connection:
        connection.row_factory = sqlite3.Row
        connection.executemany('INSERT INTO photos(path,is_kept,is_rejected,star_rating) VALUES (?,1,0,4)',
                               [(p,) for p in 'abcdefgh'])
        connection.commit()
        yield connection


def create(conn, paths, cover=None, owner='alice'):
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        return stacks.create_stack(conn, owner, paths, cover or paths[0])['stack']


def preview(conn, selected, mode='combine', **scope):
    from db.stack_regroup import preview_regroup
    with conn:
        conn.execute('BEGIN')
        return preview_regroup(conn, 'alice', selected, mode, **scope)


def apply(conn, draft, paths=None, cover=None, **scope):
    from db.stack_regroup import apply_regroup
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        return apply_regroup(conn, 'alice', draft['selected_paths'], draft['mode'],
                             paths if paths is not None else draft['paths'],
                             cover or draft['cover_path'], draft['expected_state'], **scope)


def state(conn):
    return {table: [tuple(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1,2')]
            for table in ('photos', 'photo_stacks', 'photo_stack_members', 'organization_clock',
                          'organization_revisions', 'organization_history')}


def member_paths(stack):
    return [m['path'] for m in stack['members']]


def test_combine_preview_expands_once_in_source_order(conn):
    first = create(conn, ['c', 'a', 'b'], 'b')
    second = create(conn, ['e', 'd'], 'd')
    before = state(conn)
    draft = preview(conn, ['d', 'a', 'e', 'f', 'b'])
    assert draft['selected_paths'] == ['d', 'a', 'e', 'f', 'b']
    assert draft['mode'] == 'combine'
    assert draft['paths'] == draft['affected_paths'] == ['e', 'd', 'c', 'a', 'b', 'f']
    assert draft['cover_path'] == 'd'
    assert [s['id'] for s in draft['source_stacks']] == [second['id'], first['id']]
    assert all(s['editable'] for s in draft['source_stacks'])
    assert draft['unstacked_paths'] == ['f']
    assert len(draft['expected_state']) == 64
    assert draft == preview(conn, ['d', 'a', 'e', 'f', 'b'])
    assert state(conn) == before


def test_selected_mode_retains_residual_id_and_repairs_cover(conn):
    original = create(conn, ['a', 'b', 'c', 'd'], 'a')
    draft = preview(conn, ['a', 'e'], 'selected')
    assert draft['paths'] == ['a', 'e']
    assert draft['affected_paths'] == ['a', 'b', 'c', 'd', 'e']
    result = apply(conn, draft, ['e', 'a'], 'e')
    residual = stacks.get_stack(conn, 'alice', original['id'])
    assert member_paths(residual) == ['b', 'c', 'd']
    assert residual['cover_path'] == 'b'
    assert result['stack']['id'] != original['id']
    assert member_paths(result['stack']) == ['e', 'a']
    assert result['changed'] and result['affected_paths'] == draft['affected_paths']
    assert conn.execute('SELECT count(*) FROM photos WHERE is_kept=1 AND is_rejected=0 AND star_rating=4').fetchone()[0] == 8


@pytest.mark.parametrize('mode', ['combine', 'selected'])
def test_apply_undo_restores_all_groups_and_unstacked_members(conn, mode):
    first = create(conn, ['b', 'a', 'c'], 'a')
    second = create(conn, ['e', 'd'], 'd')
    before = history.snapshot(conn, 'stack', 'alice', list('abcdef'))
    count = conn.execute('SELECT count(*) FROM organization_history').fetchone()[0]
    draft = preview(conn, ['a', 'd', 'f'], mode)
    result = apply(conn, draft, ['d', 'f', 'a'], 'f')
    assert member_paths(result['stack']) == ['d', 'f', 'a']  # Excluded b/c/e never re-expand.
    assert member_paths(stacks.get_stack(conn, 'alice', first['id'])) == ['b', 'c']
    assert stacks.get_stack(conn, 'alice', second['id']) is None
    assert stacks.get_stack_by_photo(conn, 'alice', 'e') is None
    assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == count + 1
    entry = conn.execute('SELECT * FROM organization_history WHERE id=?', (result['undo']['entry_id'],)).fetchone()
    changes = json.loads(entry['payload'])
    assert {c['path'] for c in changes} == set('abcdef')
    assert entry['part'] == entry['parts'] == 1
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.restore(conn, 'alice', changes)
    restored = history.snapshot(conn, 'stack', 'alice', list('abcdef'))
    assert {p: s['values'] for p, s in restored.items()} == {p: s['values'] for p, s in before.items()}


@pytest.mark.parametrize('race', ['source', 'unstacked', 'unstacked_aba', 'order', 'cover'])
def test_preview_to_apply_membership_race_refuses_without_writes(conn, race):
    original = create(conn, ['a', 'b', 'c'])
    draft = preview(conn, ['a', 'd'])
    if race in ('unstacked', 'unstacked_aba'):
        added = create(conn, ['d', 'e'])
        if race == 'unstacked_aba':
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                stacks.delete_stack(conn, 'alice', added['id'], added['revision'])
    else:
        paths, cover = (['b', 'a', 'c'], 'a') if race == 'order' else (['a', 'b', 'c'], 'b') if race == 'cover' else (['a', 'b'], 'a')
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            stacks.update_stack(conn, 'alice', original['id'], paths, cover, original['revision'])
    before = state(conn)
    from db.stack_regroup import apply_regroup
    # A caller catching the precondition refusal must still have no writes.
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(stacks.StackError) as error:
            apply_regroup(conn, 'alice', draft['selected_paths'], draft['mode'], draft['paths'],
                          draft['cover_path'], draft['expected_state'])
        assert error.value.status == 409
        assert state(conn) == before


@pytest.mark.parametrize('mode', ['combine', 'selected'])
def test_partial_visibility_refuses_without_disclosing_members(conn, mode):
    create(conn, ['a', 'b', 'c'])
    draft = preview(conn, ['a', 'd'], mode)
    before = state(conn)
    scope = dict(visibility_sql='photos.path != ?', visibility_params=('b',))
    for operation in (lambda: preview(conn, ['a', 'd'], mode, **scope), lambda: apply(conn, draft, **scope)):
        with pytest.raises(stacks.StackError) as error:
            operation()
        assert error.value.status == 409
        assert str(error.value) == 'Stack unavailable'
    assert state(conn) == before


def test_hidden_members_take_precedence_over_affected_limit(conn):
    paths = [f'/private-limit/{i}' for i in range(1001)]
    with conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(p,) for p in paths])
        stacks.create_stack(conn, 'alice', paths[:999], paths[0])
        stacks.create_stack(conn, 'alice', paths[999:], paths[999])
    before = state(conn)
    with pytest.raises(stacks.StackError) as error:
        preview(conn, [paths[0], paths[999]], 'selected', visibility_sql='photos.path != ?',
                visibility_params=(paths[1000],))
    assert error.value.status == 409
    assert str(error.value) == 'Stack unavailable'
    assert state(conn) == before


def test_apply_failure_rolls_back_every_source(conn):
    create(conn, ['a', 'b', 'c'])
    create(conn, ['d', 'e'])
    draft = preview(conn, ['a', 'd', 'f'], 'selected')
    with conn:
        conn.execute("CREATE TRIGGER fail_regroup BEFORE INSERT ON organization_history BEGIN SELECT RAISE(ABORT,'private failure'); END")
    before = state(conn)
    with pytest.raises(sqlite3.IntegrityError):
        apply(conn, draft)
    assert state(conn) == before


def test_noop_has_no_history_or_revision_write(conn):
    original = create(conn, ['b', 'a', 'c'], 'a')
    draft = preview(conn, ['a', 'b'])
    assert draft['cover_path'] == 'a'
    before = state(conn)
    result = apply(conn, draft)
    assert result['stack'] == original
    assert result['changed'] is False and result['undo'] is None
    assert result['affected_paths'] == ['b', 'a', 'c']
    assert state(conn) == before


def test_final_and_affected_member_limits(conn):
    paths = [f'/limit/{i}' for i in range(1001)]
    with conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(p,) for p in paths])
    original = create(conn, paths[:999])
    allowed = preview(conn, [paths[0], paths[999]], 'selected')
    assert len(allowed['affected_paths']) == 1000
    before = state(conn)
    with pytest.raises(stacks.StackError) as error:
        preview(conn, [paths[0], paths[1000], paths[999]], 'selected')
    assert error.value.status == 422
    with pytest.raises(stacks.StackError) as error:
        apply(conn, allowed, paths, paths[0])
    assert error.value.status == 422
    assert state(conn) == before
    result = apply(conn, allowed)
    assert len(result['affected_paths']) == 1000
    assert len(member_paths(stacks.get_stack(conn, 'alice', original['id']))) == 998


@pytest.mark.parametrize('mode', ['combine', 'selected'])
def test_single_source_reuses_id_and_dissolves_one_residual(conn, mode):
    original = create(conn, ['a', 'b', 'c'], 'c')
    draft = preview(conn, ['b', 'a', 'd'], mode)
    result = apply(conn, draft, ['a', 'd', 'b'], 'b')
    assert result['stack']['id'] == original['id']
    assert member_paths(result['stack']) == ['a', 'd', 'b']
    assert stacks.get_stack_by_photo(conn, 'alice', 'c') is None
    assert conn.execute('SELECT count(*) FROM photo_stacks').fetchone()[0] == 1


def test_unstacked_create_and_other_accounts_are_independent(conn):
    bob = create(conn, ['c', 'a', 'b'], 'b', owner='bob')
    draft = preview(conn, ['a', 'd'])
    assert draft['paths'] == draft['unstacked_paths'] == draft['affected_paths'] == ['a', 'd']
    assert draft['source_stacks'] == []
    result = apply(conn, draft, ['d', 'a'], 'd')
    assert member_paths(result['stack']) == ['d', 'a']
    assert stacks.get_stack(conn, 'bob', bob['id']) == bob


@pytest.mark.parametrize('selection', [['a'], ['a', 'a'], ['a', ''], ['a', 'b\x00'], ['a', 3], ['a', 'missing']])
def test_invalid_explicit_selections_refuse_without_writes(conn, selection):
    before = state(conn)
    with pytest.raises(stacks.StackError):
        preview(conn, selection)
    assert state(conn) == before


def test_unknown_mode_refuses_with_422_and_no_writes(conn):
    before = state(conn)
    with pytest.raises(stacks.StackError) as error:
        preview(conn, ['a', 'b'], 'bogus')
    assert error.value.status == 422
    assert state(conn) == before


@pytest.mark.parametrize('digest', ['zz' * 32, None])
def test_malformed_expected_state_refuses_with_422_and_no_writes(conn, digest):
    from db.stack_regroup import apply_regroup
    create(conn, ['a', 'b', 'c'])
    before = state(conn)
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        with pytest.raises(stacks.StackError) as error:
            apply_regroup(conn, 'alice', ['a', 'd'], 'selected', ['a', 'd'], 'a', digest)
    assert error.value.status == 422
    assert state(conn) == before


def test_apply_accepts_an_upper_case_expected_state(conn):
    create(conn, ['a', 'b', 'c'])
    draft = preview(conn, ['a', 'd'], 'selected')
    draft['expected_state'] = draft['expected_state'].upper()
    assert apply(conn, draft)['changed']


@pytest.mark.parametrize('paths,cover', [(['a'], 'a'), (['a', 'a'], 'a'), (['a', 'f'], 'a'),
                                       (['a', 'b'], 'f'), (['a', 'c'], 'a')])
def test_final_membership_is_a_valid_ordered_subset_of_mode(conn, paths, cover):
    create(conn, ['a', 'b', 'c'])
    draft = preview(conn, ['a', 'b'], 'selected')
    before = state(conn)
    with pytest.raises(stacks.StackError) as error:
        apply(conn, draft, paths, cover)
    assert error.value.status == 422
    assert state(conn) == before


def test_snapshot_binds_owner_selection_order_and_mode(conn):
    from db.stack_regroup import apply_regroup
    create(conn, ['a', 'b', 'c'])
    draft = preview(conn, ['a', 'd'])
    for owner, selection, mode in [('bob', ['a', 'd'], 'combine'), ('alice', ['d', 'a'], 'combine'),
                                   ('alice', ['a', 'd'], 'selected')]:
        before = state(conn)
        with pytest.raises(stacks.StackError) as error, conn:
            conn.execute('BEGIN IMMEDIATE')
            apply_regroup(conn, owner, selection, mode, ['a', 'd'], 'a', draft['expected_state'])
        assert error.value.status == 409
        assert state(conn) == before


def test_history_size_preflight_does_not_write_even_when_caller_catches(conn, monkeypatch):
    from db.stack_regroup import apply_regroup
    create(conn, ['a', 'b', 'c'])
    draft = preview(conn, ['a', 'd'], 'selected')
    monkeypatch.setattr(history, 'MAX_BYTES', 20)
    before = state(conn)
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        writes = []
        conn.set_trace_callback(lambda sql: writes.append(sql) if sql.startswith(('INSERT', 'UPDATE', 'DELETE')) else None)
        try:
            with pytest.raises(ValueError):
                apply_regroup(conn, 'alice', ['a', 'd'], 'selected', ['a', 'd'], 'a', draft['expected_state'])
        finally:
            conn.set_trace_callback(None)
        assert writes == []
        assert state(conn) == before


def test_preview_batches_many_source_stacks_and_enforces_exact_final_limit(conn):
    paths = [f'/batch/{i}' for i in range(1000)]
    with conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(p,) for p in paths])
        for index in range(0, 1000, 2):
            stacks.create_stack(conn, 'alice', paths[index:index + 2], paths[index])
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        draft = preview(conn, paths[::2])
    finally:
        conn.set_trace_callback(None)
    assert len(draft['source_stacks']) == 500 and draft['paths'] == paths
    assert len(statements) < 40  # Batched queries, not 500 per-source reads.
    result = apply(conn, draft)
    assert member_paths(result['stack']) == paths
    assert len(result['affected_paths']) == 1000


def test_helpers_require_caller_owned_transaction(conn):
    from db.stack_regroup import apply_regroup, preview_regroup
    for operation in (lambda: preview_regroup(conn, 'alice', ['a', 'b'], 'combine'),
                      lambda: apply_regroup(conn, 'alice', ['a', 'b'], 'combine', ['a', 'b'], 'a', '0' * 64)):
        with pytest.raises(RuntimeError, match='caller-owned transaction'):
            operation()


@pytest.fixture
def http_client(conn, monkeypatch):
    from api import create_app
    from api.auth import get_optional_user
    from api import config
    from api.routers import organization_history, stacks as stack_routes
    filename = conn.execute('PRAGMA database_list').fetchone()[2]
    variable_limit = None

    @contextlib.contextmanager
    def temp_db():
        connection = sqlite3.connect(filename)
        connection.row_factory = sqlite3.Row
        if variable_limit is not None:
            connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, variable_limit)
        try:
            yield connection
        finally:
            connection.close()

    monkeypatch.setattr(stack_routes, 'get_db', temp_db)
    monkeypatch.setattr(organization_history, 'get_db', temp_db)
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    monkeypatch.setitem(config.VIEWER_CONFIG, 'password', 'test-reader')
    monkeypatch.setitem(config.VIEWER_CONFIG, 'edition_password', 'test-regroup')

    def client(user):
        nonlocal variable_limit
        if hasattr(conn, 'getlimit'):
            variable_limit = conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
        app = create_app()
        app.dependency_overrides[get_optional_user] = lambda: user
        return TestClient(app)

    return client


def test_regroup_endpoints_auth_and_wire_contract(conn, http_client):
    user = CurrentUser(user_id='alice', role='admin', edition_authenticated=True)
    client = http_client(user)
    original = create(conn, ['a', 'b', 'c'], owner='')
    body = dict(selected_paths=['a', 'd'], mode='selected')
    before = state(conn)
    response = client.post('/api/stacks/regroup/preview', json=body)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    draft = response.json()
    assert set(draft) == {'selected_paths', 'mode', 'paths', 'cover_path', 'source_stacks', 'unstacked_paths', 'affected_paths', 'expected_state'}
    assert draft['paths'] == ['a', 'd'] and draft['source_stacks'][0]['id'] == original['id']
    assert state(conn) == before
    request = {**body, 'paths': ['d', 'a'], 'cover_path': 'd', 'expected_state': draft['expected_state']}
    reader = http_client(CurrentUser(user_id='alice', role='viewer'))
    assert reader.post('/api/stacks/regroup/preview', json=body).status_code == 200
    assert reader.post('/api/stacks/regroup/apply', json=request).status_code == 403
    anonymous = http_client(CurrentUser())
    assert anonymous.post('/api/stacks/regroup/preview', json=body).status_code in (401, 403)
    assert anonymous.post('/api/stacks/regroup/apply', json=request).status_code in (401, 403)
    response = client.post('/api/stacks/regroup/apply', json=request)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    result = response.json()
    assert set(result) == {'stack', 'undo', 'affected_paths', 'changed'}
    assert result['changed'] and result['affected_paths'] == ['a', 'b', 'c', 'd']
    assert member_paths(result['stack']) == ['d', 'a']
    stale = client.post('/api/stacks/regroup/apply', json=request)
    assert stale.status_code == 409 and stale.headers['cache-control'] == 'no-store'
    undone = client.post(f"/api/organization_history/{result['undo']['entry_id']}/revert?kind=stack")
    assert undone.status_code == 200, undone.text
    assert undone.json()['changed'] == 4
    assert member_paths(stacks.get_stack(conn, '', original['id'])) == ['a', 'b', 'c']
    assert stacks.get_stack_by_photo(conn, '', 'd') is None
    assert client.post('/api/stacks', json={'paths': ['a', 'e'], 'cover_path': 'a'}).status_code == 409
    other = client.post('/api/stacks', json={'paths': ['e', 'f'], 'cover_path': 'e'}).json()['stack']
    refused = client.put('/api/stacks/' + other['id'], json={
        'paths': ['e', 'a'], 'cover_path': 'e', 'expected_revision': other['revision']})
    assert refused.status_code == 409
    assert client.get('/api/stacks/' + other['id']).json() == other


@pytest.mark.parametrize('field,value', [('mode', 'bogus'), ('expected_state', 'ab' * 16)])
def test_http_rejects_a_bad_mode_and_a_short_digest_with_422(conn, http_client, field, value):
    client = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    request = dict(selected_paths=['a', 'd'], mode='selected', paths=['a', 'd'], cover_path='a',
                   expected_state='0' * 64)
    request[field] = value
    before = state(conn)
    response = client.post('/api/stacks/regroup/apply', json=request)
    assert response.status_code == 422, response.text
    assert state(conn) == before


def test_regroup_response_schema_requires_authoritative_fields(http_client):
    client = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    schemas = client.app.openapi()['components']['schemas']
    assert set(schemas['StackRegroupPreview']['required']) == {
        'selected_paths', 'mode', 'paths', 'cover_path', 'source_stacks',
        'unstacked_paths', 'affected_paths', 'expected_state'}
    assert set(schemas['StackRegroupMutation']['required']) == {'stack', 'undo', 'affected_paths', 'changed'}


def test_preview_editability_matches_get_and_token_survives_edition_login(conn, http_client):
    original = create(conn, ['a', 'b', 'c'], owner='')
    reader = http_client(CurrentUser(user_id='alice'))
    editor = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    request = {'selected_paths': ['a', 'd'], 'mode': 'selected'}
    before = state(conn)
    drafts = []
    for client, editable in [(reader, False), (editor, True)]:
        response = client.post('/api/stacks/regroup/preview', json=request)
        assert response.status_code == 200, response.text
        draft = response.json()
        stored = client.get('/api/stacks/' + original['id'])
        assert stored.status_code == 200, stored.text
        assert draft['source_stacks'][0]['editable'] is editable
        assert draft['source_stacks'][0] == stored.json()
        drafts.append(draft)
    assert state(conn) == before
    assert drafts[0]['expected_state'] == drafts[1]['expected_state']
    apply_request = {**request, 'paths': ['a', 'd'], 'cover_path': 'a',
                     'expected_state': drafts[0]['expected_state']}
    assert reader.post('/api/stacks/regroup/apply', json=apply_request).status_code == 403
    assert state(conn) == before
    response = editor.post('/api/stacks/regroup/apply', json=apply_request)
    assert response.status_code == 200, response.text
    assert response.json()['changed'] is True
    assert member_paths(response.json()['stack']) == ['a', 'd']


def test_http_undo_refuses_intervening_residual_edit_atomically(conn, http_client):
    client = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    original = create(conn, ['a', 'b', 'c'], owner='')
    request = {'selected_paths': ['a', 'd'], 'mode': 'selected'}
    draft = client.post('/api/stacks/regroup/preview', json=request).json()
    result = client.post('/api/stacks/regroup/apply', json={**request, 'paths': ['a', 'd'], 'cover_path': 'a',
                                                         'expected_state': draft['expected_state']}).json()
    residual = stacks.get_stack(conn, '', original['id'])
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.update_stack(conn, '', residual['id'], ['c', 'b'], 'c', residual['revision'])
    before = state(conn)
    refused = client.post(f"/api/organization_history/{result['undo']['entry_id']}/revert?kind=stack")
    assert refused.status_code == 409
    assert state(conn) == before


def test_http_lock_retry_rolls_back_complete_attempt(conn, http_client, monkeypatch):
    from db import stack_regroup
    client = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    create(conn, ['a', 'b', 'c'], owner='')
    request = {'selected_paths': ['a', 'd'], 'mode': 'selected'}
    draft = client.post('/api/stacks/regroup/preview', json=request).json()
    count = conn.execute('SELECT count(*) FROM organization_history').fetchone()[0]
    real_apply = stack_regroup.apply_regroup
    attempts = []

    def locked_once(*args, **kwargs):
        result = real_apply(*args, **kwargs)
        attempts.append(result)
        if len(attempts) == 1:
            raise sqlite3.OperationalError('database is locked')
        return result

    monkeypatch.setattr(stack_regroup, 'apply_regroup', locked_once)
    result = client.post('/api/stacks/regroup/apply', json={**request, 'paths': ['a', 'd'], 'cover_path': 'a',
                                                         'expected_state': draft['expected_state']})
    assert result.status_code == 200, result.text
    assert len(attempts) == 2
    assert member_paths(result.json()['stack']) == ['a', 'd']
    assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == count + 1


def test_http_database_errors_and_history_limits_are_safe_and_atomic(conn, http_client, monkeypatch):
    client = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    create(conn, ['a', 'b', 'c'], owner='')
    request = {'selected_paths': ['a', 'd'], 'mode': 'selected'}
    draft = client.post('/api/stacks/regroup/preview', json=request).json()
    request.update(paths=['a', 'd'], cover_path='a', expected_state=draft['expected_state'])
    before = state(conn)
    with monkeypatch.context() as patch:
        patch.setattr(history, 'MAX_BYTES', 20)
        refused = client.post('/api/stacks/regroup/apply', json=request)
        assert refused.status_code == 422 and refused.headers['cache-control'] == 'no-store'
        assert state(conn) == before
    with conn:
        conn.execute("CREATE TRIGGER fail_http_regroup BEFORE INSERT ON organization_history BEGIN SELECT RAISE(ABORT,'/private/server/path'); END")
    refused = client.post('/api/stacks/regroup/apply', json=request)
    assert refused.status_code == 500 and refused.headers['cache-control'] == 'no-store'
    assert '/private/server/path' not in refused.text
    assert state(conn) == before


@pytest.mark.parametrize('mode', ['combine', 'selected'])
def test_excluded_sources_do_not_prevent_exact_stack_noop(conn, mode):
    original = create(conn, ['b', 'a', 'c'], 'a')
    excluded = create(conn, ['d', 'e'])
    draft = preview(conn, ['a', 'b', 'c', 'd', 'f'], mode)
    before, changes = state(conn), conn.total_changes
    result = apply(conn, draft, ['b', 'a', 'c'], 'a')
    assert result['changed'] is False and result['undo'] is None
    assert result['stack'] == original
    assert conn.total_changes == changes
    assert state(conn) == before
    assert stacks.get_stack(conn, 'alice', excluded['id']) == excluded


@pytest.mark.parametrize('mode', ['combine', 'selected'])
@pytest.mark.parametrize('remaining', [0, 1, 2])
def test_only_contributing_source_is_changed_and_id_reuse_depends_on_residual(conn, mode, remaining):
    original = create(conn, list('abcd')[:2 + remaining])
    excluded = create(conn, ['e', 'f'])
    draft = preview(conn, ['a', 'b', 'e', 'g', 'h'], mode)
    excluded_before = history.snapshot(conn, 'stack', 'alice', ['e', 'f', 'h'])
    result = apply(conn, draft, ['b', 'g', 'a'], 'b')
    assert (result['stack']['id'] == original['id']) is (remaining < 2)
    assert member_paths(result['stack']) == ['b', 'g', 'a']
    assert set(result['affected_paths']) == set(list('abcd')[:2 + remaining] + ['g'])
    assert stacks.get_stack(conn, 'alice', excluded['id']) == excluded
    assert history.snapshot(conn, 'stack', 'alice', ['e', 'f', 'h']) == excluded_before
    if remaining == 2:
        assert member_paths(stacks.get_stack(conn, 'alice', original['id'])) == ['c', 'd']
    elif remaining == 1:
        assert stacks.get_stack_by_photo(conn, 'alice', 'c') is None
    changes = json.loads(conn.execute('SELECT payload FROM organization_history WHERE id=?',
                                     (result['undo']['entry_id'],)).fetchone()[0])
    assert {change['path'] for change in changes} == set(result['affected_paths'])


@pytest.mark.parametrize('mode', ['combine', 'selected'])
@pytest.mark.parametrize('final', [['b', 'a'], ['g', 'h']])
def test_http_excluded_source_edits_do_not_block_undo(conn, http_client, mode, final):
    client = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    original = create(conn, ['a', 'b'], owner='')
    excluded = create(conn, ['c', 'd'], owner='')
    body = dict(selected_paths=['a', 'b', 'c', 'g', 'h'], mode=mode)
    draft = client.post('/api/stacks/regroup/preview', json=body).json()
    before = history.snapshot(conn, 'stack', '', ['c', 'd'])
    response = client.post('/api/stacks/regroup/apply', json={**body, 'paths': final,
        'cover_path': final[0], 'expected_state': draft['expected_state']})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['changed'] is True and set(result['affected_paths']) == set(final)
    assert history.snapshot(conn, 'stack', '', ['c', 'd']) == before
    if final == ['b', 'a']:
        assert result['stack']['id'] == original['id']
    else:
        assert stacks.get_stack(conn, '', original['id']) == original
    edited = client.put('/api/stacks/' + excluded['id'], json={
        'paths': ['d', 'c'], 'cover_path': 'd', 'expected_revision': excluded['revision']})
    assert edited.status_code == 200, edited.text
    undone = client.post(f"/api/organization_history/{result['undo']['entry_id']}/revert?kind=stack")
    assert undone.status_code == 200, undone.text
    assert undone.json()['changed'] == 2
    assert client.get('/api/stacks/' + excluded['id']).json() == edited.json()['stack']
    assert stacks.get_stack(conn, '', original['id'])['members'] == original['members']
    assert stacks.get_stack_by_photo(conn, '', 'g') is None
    assert stacks.get_stack_by_photo(conn, '', 'h') is None


@pytest.mark.parametrize('mode', ['combine', 'selected'])
def test_excluded_sources_still_require_current_preview_and_full_visibility(conn, mode):
    create(conn, ['a', 'b'])
    excluded = create(conn, ['c', 'd'])
    draft = preview(conn, ['a', 'b', 'c'], mode)
    before = state(conn)
    with pytest.raises(stacks.StackError):
        apply(conn, draft, ['a', 'b'], 'a', visibility_sql='photos.path != ?', visibility_params=('d',))
    assert state(conn) == before
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.update_stack(conn, 'alice', excluded['id'], ['d', 'c'], 'd', excluded['revision'])
    before = state(conn)
    with pytest.raises(stacks.StackError):
        apply(conn, draft, ['a', 'b'], 'a')
    assert state(conn) == before


@pytest.mark.parametrize('mode', ['combine', 'selected'])
def test_http_excluded_sources_leave_identical_stack_unchanged(conn, http_client, mode):
    client = http_client(CurrentUser(user_id='alice', edition_authenticated=True))
    original = create(conn, ['b', 'a'], 'a', owner='')
    create(conn, ['c', 'd'], owner='')
    body = dict(selected_paths=['a', 'b', 'c', 'e'], mode=mode)
    draft = client.post('/api/stacks/regroup/preview', json=body).json()
    before = state(conn)
    response = client.post('/api/stacks/regroup/apply', json={**body, 'paths': ['b', 'a'],
        'cover_path': 'a', 'expected_state': draft['expected_state']})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['changed'] is False and result['undo'] is None
    assert result['stack']['id'] == original['id'] and result['stack']['revision'] == original['revision']
    assert result['affected_paths'] == ['b', 'a']
    assert state(conn) == before


@pytest.mark.skipif(not hasattr(sqlite3.Connection, 'setlimit'),
                    reason='Python 3.10 cannot lower the SQLite connection variable limit')
@pytest.mark.parametrize(('grants', 'source_count'), [(350, 299), (499, 2)])
def test_regroup_http_reserves_legacy_bindings_through_preview_apply_and_undo(
        conn, http_client, monkeypatch, grants, source_count):
    from api import config, db_helpers
    from api.routers import stacks as routes

    paths = [f'/regroup-budget/visible/{i:04}.jpg' for i in range(source_count * 2)]
    hidden = '/regroup-budget/hidden/member.jpg'
    with conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(p,) for p in [*paths, hidden]])
        for index in range(0, len(paths), 2):
            stacks.create_stack(conn, 'alice', paths[index:index + 2], paths[index])
        other = stacks.create_stack(conn, 'bob', [paths[0], hidden], paths[0])['stack']
    other_before = stacks.get_stack(conn, 'bob', other['id'])
    monkeypatch.setattr(db_helpers, 'is_multi_user_enabled', lambda: True)
    monkeypatch.setattr(db_helpers, '_CASE_INSENSITIVE_HOST', False)
    monkeypatch.setattr(routes, 'is_multi_user_enabled', lambda: True)
    directories = ['/regroup-budget/visible/',
                   *[f'/regroup-budget/unrelated-{i}/' for i in range(grants - 1)]]
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        owner: {'directories': directories} for owner in ('alice', 'bob')})
    clause, params = db_helpers.get_visibility_clause('alice')
    assert len(params) == grants * 2
    conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
    assert conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) == 999
    # Confirm that the test connection really enforces the legacy ceiling.
    with pytest.raises(sqlite3.OperationalError, match='too many SQL variables'):
        conn.execute('SELECT 1 WHERE 1 IN (' + ','.join('?' for _ in range(1000)) + ')', [1] * 1000)
    client = http_client(CurrentUser(user_id='alice', role='admin', edition_authenticated=True))
    selected = paths[::2]
    assert len(selected) == source_count
    first = stacks.get_stack_by_photo(conn, 'alice', paths[0], visibility_sql=clause, visibility_params=params)
    assert member_paths(first) == paths[:2]
    before = state(conn)
    response = client.post('/api/stacks/regroup/preview', json={'selected_paths': selected, 'mode': 'combine'})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['paths'] == draft['affected_paths'] == paths
    assert len(draft['source_stacks']) == source_count
    assert other['id'] not in [source['id'] for source in draft['source_stacks']]
    assert hidden not in response.text
    assert client.get('/api/stacks/' + other['id']).json() is None
    assert state(conn) == before
    request = {key: draft[key] for key in ('selected_paths', 'mode', 'paths', 'cover_path', 'expected_state')}
    other_client = http_client(CurrentUser(user_id='bob', role='admin', edition_authenticated=True))
    assert other_client.post('/api/stacks/regroup/apply', json=request).status_code == 409
    assert state(conn) == before
    response = client.post('/api/stacks/regroup/apply', json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert member_paths(result['stack']) == paths
    assert stacks.get_stack(conn, 'bob', other['id']) == other_before
    assert conn.execute("SELECT COUNT(*) FROM photo_stacks WHERE owner='alice'").fetchone()[0] == 1
    # Shared ordinary GET and strict update must retain their authorization and conflict semantics.
    stack_id = result['stack']['id']
    assert member_paths(client.get('/api/stacks/' + stack_id).json()) == paths
    listed = client.get('/api/organization_history')
    assert listed.status_code == 200, listed.text
    assert result['undo']['entry_id'] in [entry['id'] for entry in listed.json()['entries']]
    assert client.post('/api/stacks', json={'paths': paths[:2], 'cover_path': paths[0]}).status_code == 409
    assert client.put('/api/stacks/' + stack_id, json={
        'paths': [*paths, hidden], 'cover_path': paths[0],
        'expected_revision': result['stack']['revision']}).status_code == 409
    response = client.post(f"/api/organization_history/{result['undo']['entry_id']}/revert?kind=stack")
    assert response.status_code == 200, response.text
    assert response.json()['changed'] == len(paths)
    assert state(conn)['photo_stack_members'] == before['photo_stack_members']
    assert state(conn)['photos'] == before['photos']
    assert conn.execute("SELECT COUNT(*) FROM photo_stacks WHERE owner='alice'").fetchone()[0] == source_count
    assert stacks.get_stack(conn, 'bob', other['id']) == other_before
    # A hidden expanded member is refused before writing, even when the selected members are visible.
    source = stacks.get_stack_by_photo(conn, 'alice', paths[-2])
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        stacks.update_stack(conn, 'alice', source['id'], [paths[-2], hidden], paths[-2], source['revision'])
    before_refusal = state(conn)
    for route, body in [('preview', {'selected_paths': selected, 'mode': 'combine'}), ('apply', request)]:
        response = client.post('/api/stacks/regroup/' + route, json=body)
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == 'Stack unavailable'
        assert state(conn) == before_refusal


@pytest.mark.parametrize('wrong_parent', [True, False])
def test_regroup_does_not_trust_cross_owner_memberships(conn, wrong_parent):
    alice = create(conn, ['a', 'b'])
    bob = create(conn, ['c', 'd'], owner='bob')
    # External writers can omit foreign_keys; parent ownership must still gate source authorization.
    assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 0
    with conn:
        conn.execute('INSERT INTO photo_stack_members(stack_id,owner,photo_path,position) VALUES (?,?,?,2)',
                     (bob['id'] if wrong_parent else alice['id'], 'alice' if wrong_parent else 'bob', 'h'))
    before = state(conn)
    if wrong_parent:
        with pytest.raises(stacks.StackError, match='Stack unavailable'):
            preview(conn, ['a', 'h'])
    else:
        draft = preview(conn, ['a', 'e'], visibility_sql='photos.path != ?', visibility_params=['h'])
        assert draft['paths'] == ['a', 'b', 'e']
        assert [source['id'] for source in draft['source_stacks']] == [alice['id']]
    assert state(conn) == before
