"""Authorized logical review snapshots; original file labels are never mutated."""
from fastapi import HTTPException

from api import config
from api.db_helpers import get_photos_from_clause, get_preference_columns, get_visibility_clause
from db import logical_review
from db.logical_assets import AssetConflict


def snapshot(conn, asset_id, user_id):
    group = conn.execute('SELECT revision FROM logical_assets WHERE id=?', (asset_id,)).fetchone()
    paths = [row[0] for row in conn.execute(
        'SELECT photo_path FROM logical_asset_members WHERE asset_id=? ORDER BY position', (asset_id,))]
    if group is None or not paths:
        raise HTTPException(404, 'Logical review unavailable')
    source, source_params = get_photos_from_clause(user_id)
    visibility, params = get_visibility_clause(user_id)
    fields = sorted(logical_review.FIELDS)
    expressions = get_preference_columns(user_id)
    columns = ','.join(expressions[field] for field in fields)
    rows = conn.execute(f"SELECT photos.path,{columns} FROM {source} "
                        f"WHERE photos.path IN ({','.join('?' for _ in paths)}) AND ({visibility})",
                        [*source_params, *paths, *params]).fetchall()
    if len(rows) != len(paths):
        raise HTTPException(404, 'Logical review unavailable')
    labels = {row[0]: dict(zip(fields, row[1:])) for row in rows}
    owner = str(user_id) if user_id and config.is_multi_user_enabled() else ''
    state = logical_review.read(conn, asset_id, owner, labels)
    return {'asset_id': asset_id, 'group_revision': group[0], **state}, owner, labels, visibility, params


def read(conn, asset_id, user_id):
    return snapshot(conn, asset_id, user_id)[0]


def apply(conn, body, user, *, record_history=True):
    from db import logical_history

    _, owner, labels, visibility, params = snapshot(conn, body.asset_id, user.user_id)
    try:
        with logical_review._transaction(conn):
            before = logical_history.capture(conn, body.asset_id, owner, labels) if record_history else None
            options = dict(visibility_sql=visibility, visibility_params=params, file_labels=labels, input_token=body.input_token)
            if body.reset:
                logical_review.reset_fields(conn, body.asset_id, owner, body.group_revision, body.revision, body.reset, **options)
            else:
                logical_review.set_fields(conn, body.asset_id, owner, body.group_revision, body.revision, body.patch,
                                          origin='agent' if user.is_agent_request else 'user', **options)
            result = read(conn, body.asset_id, user.user_id)
            if before is not None:
                after = logical_history.capture(conn, body.asset_id, owner, labels)
                logical_history.record(conn, user.user_id or '', owner, {body.asset_id: before}, {body.asset_id: after})
    except AssetConflict as error:
        raise HTTPException(409, str(error)) from None
    return result


async def attach_async(conn, photos, user_id):
    """Attach account review state without changing physical labels or grouping rows.

    All reads share the caller's transaction. Hidden group members suppress the
    entire annotation. Collection projection will choose which identity to show.
    """
    import json
    from api.database import run_sync

    if not photos:
        return
    if not conn.in_transaction:
        raise AssetConflict('A catalog read transaction is required')

    async def rows(sql, params=()):
        cursor = await conn.execute(sql, params)
        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()

    paths_json = json.dumps(list({photo['path'] for photo in photos}))
    memberships = await rows('SELECT photo_path,asset_id FROM logical_asset_members '
                             'WHERE photo_path IN (SELECT value FROM json_each(?))', [paths_json])
    if not memberships:
        return
    ids_json = json.dumps(sorted({row[1] for row in memberships}))
    source, source_params = get_photos_from_clause(user_id)
    visibility, params = get_visibility_clause(user_id)
    fields = sorted(logical_review.FIELDS)
    expressions = get_preference_columns(user_id)
    columns = ','.join(expressions[field] for field in fields)
    members = await rows('SELECT asset_id,photo_path FROM logical_asset_members '
                         'WHERE asset_id IN (SELECT value FROM json_each(?))', [ids_json])
    visible = await rows(f'SELECT photos.path,{columns} FROM {source} WHERE photos.path IN '
                         '(SELECT photo_path FROM logical_asset_members WHERE asset_id IN '
                         f'(SELECT value FROM json_each(?))) AND ({visibility})',
                         [*source_params, ids_json, *params])
    labels = {row[0]: dict(zip(fields, row[1:])) for row in visible}
    grouped = {}
    for key, path in members:
        grouped.setdefault(key, set()).add(path)
    allowed = {key for key, paths in grouped.items() if paths <= labels.keys()}
    if not allowed:
        return
    # Query private review data only for fully authorized groups and this owner.
    ids_json = json.dumps(sorted(allowed))
    owner = str(user_id) if user_id and config.is_multi_user_enabled() else ''
    seeds = dict(await rows('SELECT asset_id,photo_path FROM logical_review_seeds '
                            'WHERE asset_id IN (SELECT value FROM json_each(?))', [ids_json]))
    versions = dict(await rows('SELECT asset_id,revision FROM logical_review_versions '
                               'WHERE owner=? AND asset_id IN (SELECT value FROM json_each(?))', [owner, ids_json]))
    overrides = {}
    for key, field, value, origin in await rows(
            'SELECT asset_id,field,value,origin FROM logical_review_fields '
            'WHERE owner=? AND asset_id IN (SELECT value FROM json_each(?)) ORDER BY asset_id,field', [owner, ids_json]):
        overrides.setdefault(key, []).append((field, value, origin))
    groups = await rows('SELECT id,primary_path,revision FROM logical_assets '
                        'WHERE id IN (SELECT value FROM json_each(?))', [ids_json])
    databases = await rows('PRAGMA database_list')
    filename = next(row[2] for row in databases if row[1] == 'main')
    database = await run_sync(logical_review.database_identity, filename, id(conn))
    states = {}
    for key, primary, revision in groups:
        state = logical_review.resolve(key, owner, labels, grouped[key], seeds.get(key), overrides.get(key, []),
                                       versions.get(key, 0), database, (primary, revision))
        states[key] = {'asset_id': key, 'group_revision': revision, **state}
    by_path = dict(memberships)
    for photo in photos:
        state = states.get(by_path.get(photo['path']))
        if state is not None:
            photo['logical_review'] = state


def apply_path(conn, path, user, action, rating=None):
    """Adapt direct review commands to logical authority in the caller's write lock.

    None means truly ungrouped, never a hidden or partially authorized group.
    Direct commands have absolute/set-or-current-toggle semantics; the
    snapshot API remains the revision-guarded browser path.
    """
    from types import SimpleNamespace

    if not conn.in_transaction:
        raise AssetConflict('A catalog transaction is required')
    membership = conn.execute('SELECT asset_id FROM logical_asset_members WHERE photo_path=?', (path,)).fetchone()
    if membership is None:
        return None
    state = read(conn, membership[0], user.user_id)
    values = state['values']
    if action == 'rating':
        patch = {'star_rating': rating}
        response = {'success': True, 'rating': rating}
    elif action == 'favorite':
        enabled = int(not values['is_favorite'])
        patch = {'is_favorite': enabled}
        if enabled:
            patch.update(is_kept=int(bool(values['is_kept'])), is_rejected=0)
        response = {'success': True, 'is_favorite': bool(enabled), 'is_rejected': False if enabled else None}
    elif action == 'reject':
        enabled = int(not values['is_rejected'])
        patch = {'is_rejected': enabled, 'is_kept': 0}
        if enabled:
            patch.update(star_rating=0, is_favorite=0)
        response = {'success': True, 'is_rejected': bool(enabled), 'is_kept': False if enabled else None,
                    'star_rating': 0 if enabled else None, 'is_favorite': False if enabled else None}
    else:
        raise ValueError('Unsupported review action')
    change = SimpleNamespace(asset_id=state['asset_id'], group_revision=state['group_revision'],
                             revision=state['revision'], input_token=state['input_token'], patch=patch, reset=[])
    apply(conn, change, user)
    return response
