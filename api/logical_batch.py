"""Atomic batch review split between logical identities and independent files."""
import json
from types import SimpleNamespace

from fastapi import HTTPException

from api import logical_reviews, organization_capture
from db import logical_history
from db.logical_assets import AssetConflict
from api.config import is_multi_user_enabled
from api.db_helpers import get_existing_columns, get_visibility_clause, snapshot_labels, read_labels, record_label_origin
from api.logical_collection import source, membership


def culling_decision(conn, paths, user_id, agent, rejected):
    """Keep/Reject without clearing culling's existing stars and favorites."""
    from api.routers.faces import BatchWriteSql

    kept = int(not rejected)
    rejected = int(rejected)
    user = SimpleNamespace(user_id=user_id, is_agent_request=agent)
    body = SimpleNamespace(filters=None, photo_paths=list(paths), exclude=[])
    sql = BatchWriteSql(
        multi_user=(
            'INSERT INTO user_preferences(user_id,photo_path,is_kept,is_rejected) VALUES (?,?,?,?) '
            'ON CONFLICT(user_id,photo_path) DO UPDATE SET is_kept=excluded.is_kept,is_rejected=excluded.is_rejected'
        ),
        multi_user_row=lambda path: (user_id, path, kept, rejected),
        single_user='UPDATE photos SET is_kept=?,is_rejected=? WHERE path IN ({placeholders})',
        single_user_prefix=(kept, rejected),
        filter_multi_user=(
            'INSERT INTO user_preferences(user_id,photo_path,is_kept,is_rejected) SELECT ?,photos.path,?,? FROM {scope} '
            'ON CONFLICT(user_id,photo_path) DO UPDATE SET is_kept=excluded.is_kept,is_rejected=excluded.is_rejected'
        ),
        filter_multi_user_prefix=(user_id, kept, rejected),
        filter_single_user='UPDATE photos SET is_kept=?,is_rejected=? WHERE path IN (SELECT photos.path FROM {scope})',
    )
    return apply(conn, body, user, sql, {'is_kept': kept, 'is_rejected': rejected}, rejected)['count']


def apply(conn, body, user, sql, patch, review_rejected):
    from api.routers.faces import _write_paths, BatchReviewRequest, logger
    from api.routers.gallery import gallery_scope_sql, _raise_422_for_invalid_gallery_params
    from pydantic import ValidationError

    if body.filters is not None:
        try:
            collection, where, params = gallery_scope_sql(conn, body.filters, user.user_id, body.exclude, logical=True)
        except ValidationError as error:
            _raise_422_for_invalid_gallery_params(error, logger, 'Logical batch filter validation failed: %s')
    else:
        visibility, values = get_visibility_clause(user.user_id)
        multi_user = is_multi_user_enabled()
        query = source(sorted(get_existing_columns(conn)), owner=(user.user_id or '') if multi_user else '',
                       multi_user=multi_user, visibility_sql=visibility, visibility_params=values)
        selected = membership('SELECT value AS photo_path FROM json_each(?)', [json.dumps(body.photo_paths)])
        collection, where, params = query.sql, f' WHERE {selected.sql}', [*query.params, *selected.params]
        if body.exclude:
            excluded = membership('SELECT value AS photo_path FROM json_each(?)', [json.dumps(body.exclude)])
            where += f' AND NOT ({excluded.sql})'
            params.extend(excluded.params)
    rows = conn.execute(f'SELECT photos.path,photos._logical_asset_id FROM {collection}{where}', params).fetchall()
    paths = [row[0] for row in rows if row[1] is None]
    if paths and conn.execute(
            'SELECT 1 FROM logical_asset_members WHERE photo_path IN (SELECT value FROM json_each(?)) LIMIT 1',
            [json.dumps(paths)]).fetchone():
        # A partially authorized group is redacted in collection reads. Never
        # reinterpret that redaction as permission to write its physical files.
        raise HTTPException(404, 'Photo review unavailable')
    keys = sorted({row[1] for row in rows if row[1] is not None})
    # Capture every logical precondition before the first label mutation.
    states = [logical_reviews.read(conn, key, user.user_id) for key in keys]
    history = organization_capture.begin(conn, user.user_id, 'review', paths)
    captured = {}
    owner = history[0]
    for key in keys:
        _, group_owner, labels, _, _ = logical_reviews.snapshot(conn, key, user.user_id)
        if group_owner != owner:
            raise HTTPException(409, 'Review scope changed')
        captured[key] = logical_history.capture(conn, key, owner, labels)
    deferred = bool(keys) and organization_capture.defer_logical(conn, user.user_id, owner, captured)
    before = snapshot_labels(conn, user.is_agent_request, user.user_id, paths)
    origin_paths = paths
    if review_rejected is not None and not user.is_agent_request:
        labels = read_labels(conn, user.user_id, paths)
        origin_paths = [path for path in paths if labels[path].rejected != review_rejected]
    for state in states:
        change = dict(patch)
        if change.get('is_favorite') == 1 and 'is_kept' not in change:
            change.update(is_kept=int(bool(state['values']['is_kept'])), is_rejected=0)
        body_state = SimpleNamespace(asset_id=state['asset_id'], group_revision=state['group_revision'],
                                     revision=state['revision'], input_token=state['input_token'], patch=change, reset=[])
        logical_reviews.apply(conn, body_state, user, record_history=False)
    for offset in range(0, len(paths), 900):
        _write_paths(conn, paths[offset:offset + 900], user, sql)
    record_label_origin(conn, user.is_agent_request, user.user_id, origin_paths, before)
    if keys and not deferred:
        after = {}
        for key in keys:
            _, _, labels, _, _ = logical_reviews.snapshot(conn, key, user.user_id)
            after[key] = logical_history.capture(conn, key, owner, labels)
        try:
            entries = logical_history.record(conn, user.user_id or '', owner, captured, after, physical_before=history[1])
        except AssetConflict as error:
            raise HTTPException(409, str(error)) from None
    elif not keys:
        entries = organization_capture.finish(conn, user.user_id, 'review', history)
    else:
        entries = []
    result = {'success': True, 'count': len(paths) + len(keys)}
    if keys:
        result['logical_asset_ids'] = keys
        result['logical_member_paths'] = sorted({path for key in keys for (path,) in conn.execute(
            'SELECT photo_path FROM logical_asset_members WHERE asset_id=?', (key,))})
    elif (isinstance(body, BatchReviewRequest) and body.decision == 'rejected'
          and body.filters is None and len(body.photo_paths or ()) == 1 and len(entries) == 1):
        result['undo_entry_id'] = entries[0]
    return result
