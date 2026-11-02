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


def apply(conn, body, user):
    _, owner, labels, visibility, params = snapshot(conn, body.asset_id, user.user_id)
    try:
        options = dict(visibility_sql=visibility, visibility_params=params, file_labels=labels, input_token=body.input_token)
        if body.reset:
            logical_review.reset_fields(conn, body.asset_id, owner, body.group_revision, body.revision, body.reset, **options)
        else:
            logical_review.set_fields(conn, body.asset_id, owner, body.group_revision, body.revision, body.patch,
                                      origin='agent' if user.is_agent_request else 'user', **options)
    except AssetConflict as error:
        raise HTTPException(409, str(error)) from None
    return read(conn, body.asset_id, user.user_id)


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
