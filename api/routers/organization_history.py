"""Private, visibility-checked organization history and whole-entry revert."""
import json
import logging
import sqlite3
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.auth import CurrentUser, require_edition
from api.database import get_db
from api.db_helpers import (
    after_commit, get_visibility_clause, is_locked_error, record_label_origin, retry_on_locked,
)
from api.models.organization_history import OrganizationHistory, OrganizationRevert
from db.organization_history import FIELDS, record, snapshot
from db import stacks
from db.maintenance import evict_derived_stats_cache
from api.routers.stacks import stack_owner

router = APIRouter(tags=['organization_history'])


def _visible(conn: sqlite3.Connection, user: CurrentUser, changes: list[dict[str, Any]]) -> bool:
    clause, params = get_visibility_clause(user.user_id)
    paths = [change['path'] for change in changes]
    return len(stacks.visible_paths(conn, paths, clause, params)) == len(paths)


def _logical_context(conn, user, entry, changes):
    from api import logical_reviews

    labels, visible_changes = {}, []
    from api.config import is_multi_user_enabled
    owner = (user.user_id or '') if is_multi_user_enabled() else ''
    if owner != entry['scope']:
        return None
    visibility, params = get_visibility_clause(user.user_id)
    for change in changes:
        if 'asset_id' not in change:
            if not _visible(conn, user, [change]):
                return None
            visible_changes.append({key: change[key] for key in ('path', 'before', 'after', 'revision')})
            continue
        try:
            _, current_owner, current_labels, visibility, params = logical_reviews.snapshot(conn, change['asset_id'], user.user_id)
        except HTTPException as error:
            if error.status_code == 404:
                return None
            raise
        if current_owner != entry['scope']:
            return None
        owner = current_owner
        labels.update(current_labels)
        path = conn.execute('SELECT photo_path FROM logical_asset_members WHERE asset_id=? ORDER BY position LIMIT 1',
                            (change['asset_id'],)).fetchone()[0]
        # Internal overrides/tokens and historical native paths stay private.
        visible_changes.append(dict(path=path, before=change['before'], after=change['after'], revision=change['revision']))
    return (owner, labels, visibility, params, visible_changes) if owner is not None else None


@router.get('/api/organization_history', response_model=OrganizationHistory)
def list_history(response: Response, user: CurrentUser = Depends(require_edition)) -> dict[str, Any]:
    response.headers['Cache-Control'] = 'no-store'
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        entries = []
        for row in conn.execute("SELECT * FROM organization_history WHERE (owner=? AND kind!='stack') OR (owner=? AND kind='stack') ORDER BY id DESC LIMIT 50", (user.user_id or '', stack_owner(user.user_id))):
            changes = json.loads(row['payload'])
            if row['kind'] == 'logical_review':
                context = _logical_context(conn, user, row, changes)
                if context is None:
                    continue
                changes = context[4]
            if row['kind'] == 'logical_review' or _visible(conn, user, changes):
                entries.append({**{key: row[key] for key in ('id', 'kind', 'created_at', 'part', 'parts', 'reverted')}, 'changes': changes})
        return {'entries': entries}


@router.post('/api/organization_history/{entry_id}/revert', response_model=OrganizationRevert)
@retry_on_locked()
def revert_history(entry_id: int, response: Response, user: CurrentUser = Depends(require_edition),
                   kind: Annotated[Optional[Literal['stack']], Query(description='Refuse an entry of another kind')] = None
                   ) -> dict[str, int]:
    response.headers['Cache-Control'] = 'no-store'
    try:
        return _revert(entry_id, user, kind)
    except sqlite3.Error as exc:
        if is_locked_error(exc):
            raise
        logging.getLogger(__name__).exception('Database error reverting organization history')
        raise HTTPException(500, 'Could not restore history', headers={'Cache-Control': 'no-store'}) from exc


def _revert(entry_id: int, user: CurrentUser, kind_filter: Optional[str] = None) -> dict[str, int]:
    headers = {'Cache-Control': 'no-store'}
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        entry = conn.execute("SELECT * FROM organization_history WHERE id=? AND ((owner=? AND kind!='stack') OR (owner=? AND kind='stack'))", (entry_id, user.user_id or '', stack_owner(user.user_id))).fetchone()
        if not entry or (kind_filter is not None and entry['kind'] != kind_filter):
            raise HTTPException(404, 'History entry not found', headers=headers)
        changes = json.loads(entry['payload'])
        if entry['kind'] == 'logical_review':
            from db import logical_history
            from db.logical_assets import AssetConflict
            context = _logical_context(conn, user, entry, changes)
            if context is None:
                raise HTTPException(404, 'History entry not available', headers=headers)
            owner, labels, visibility, params, _ = context
            try:
                changed = logical_history.restore(conn, user.user_id or '', owner, entry_id, labels,
                                                  visibility_sql=visibility, visibility_params=params)
            except AssetConflict:
                raise HTTPException(409, 'Photos changed since this action; nothing was restored', headers=headers) from None
            physical_paths = [change['path'] for change in changes if 'asset_id' not in change]
            if physical_paths:
                record_label_origin(conn, user.is_agent_request, user.user_id, physical_paths)
            evict_derived_stats_cache(conn)
            conn.commit()
            after_commit()
            return {'changed': changed}
        if not _visible(conn, user, changes):
            if entry['kind'] == 'stack':
                raise HTTPException(409, 'Stack unavailable', headers=headers)
            raise HTTPException(404, 'History entry not available', headers=headers)
        kind, scope = entry['kind'], entry['scope']
        current = snapshot(conn, kind, scope, [change['path'] for change in changes])
        if entry['reverted'] or any(current[c['path']]['values'] != c['after'] or current[c['path']]['revision'] != c['revision'] for c in changes):
            raise HTTPException(409, 'Photos changed since this action; nothing was restored', headers=headers)
        if kind == 'stack':
            try:
                stacks.restore(conn, scope, changes)
            except stacks.StackError as exc:
                raise HTTPException(exc.status, str(exc), headers=headers) from exc
        fields = FIELDS.get(kind, ())
        for change in changes if kind != 'stack' else []:
            if kind == 'review' and scope:
                columns = ','.join(fields)
                updates = ','.join(f'{field}=excluded.{field}' for field in fields)
                marks = ','.join('?' for _ in range(2 + len(fields)))
                conn.execute(f'INSERT INTO user_preferences(user_id,photo_path,{columns}) VALUES ({marks}) ON CONFLICT(user_id,photo_path) DO UPDATE SET {updates}',
                             [scope, change['path'], *change['before']])
            else:
                conn.execute(f"UPDATE photos SET {','.join(f'{field}=?' for field in fields)} WHERE path=?",
                             [*change['before'], change['path']])
        record(conn, entry['owner'], kind, scope, current)
        conn.execute('UPDATE organization_history SET reverted=1 WHERE id=?', (entry_id,))
        if kind == 'review':
            record_label_origin(conn, user.is_agent_request, user.user_id, list(current))
        evict_derived_stats_cache(conn)
    after_commit()
    return {'changed': len(changes)}
