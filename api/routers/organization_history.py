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


@router.get('/api/organization_history', response_model=OrganizationHistory)
def list_history(response: Response, user: CurrentUser = Depends(require_edition)) -> dict[str, Any]:
    response.headers['Cache-Control'] = 'no-store'
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        entries = []
        for row in conn.execute("SELECT * FROM organization_history WHERE (owner=? AND kind!='stack') OR (owner=? AND kind='stack') ORDER BY id DESC LIMIT 50", (user.user_id or '', stack_owner(user.user_id))):
            changes = json.loads(row['payload'])
            if _visible(conn, user, changes):
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
