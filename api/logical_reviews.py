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
