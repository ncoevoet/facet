"""Private, visibility-checked organization history and whole-entry revert."""
import json
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from api.auth import CurrentUser, require_edition
from api.database import get_db
from api.db_helpers import get_visibility_clause, is_locked_error, retry_on_locked
from api.models.organization_history import OrganizationHistory, OrganizationRevert
from db.organization_history import FIELDS, record, snapshot

router = APIRouter(tags=['organization_history'])


def _visible(conn: sqlite3.Connection, user: CurrentUser, changes: list[dict[str, Any]]) -> bool:
    clause, params = get_visibility_clause(user.user_id)
    for start in range(0, len(changes), 400):
        paths = [change['path'] for change in changes[start:start + 400]]
        marks = ','.join('?' for _ in paths)
        count = conn.execute(f'SELECT COUNT(*) FROM photos WHERE path IN ({marks}) AND {clause}', [*paths, *params]).fetchone()[0]
        if count != len(paths):
            return False
    return True


@router.get('/api/organization_history', response_model=OrganizationHistory)
def list_history(response: Response, user: CurrentUser = Depends(require_edition)) -> dict[str, Any]:
    response.headers['Cache-Control'] = 'no-store'
    with get_db() as conn, conn:
        conn.execute('BEGIN')
        entries = []
        for row in conn.execute('SELECT * FROM organization_history WHERE owner=? ORDER BY id DESC LIMIT 50', (user.user_id or '',)):
            changes = json.loads(row['payload'])
            if _visible(conn, user, changes):
                entries.append({**{key: row[key] for key in ('id', 'kind', 'created_at', 'part', 'parts', 'reverted')}, 'changes': changes})
        return {'entries': entries}


@router.post('/api/organization_history/{entry_id}/revert', response_model=OrganizationRevert)
@retry_on_locked()
def revert_history(entry_id: int, response: Response, user: CurrentUser = Depends(require_edition)) -> dict[str, int]:
    response.headers['Cache-Control'] = 'no-store'
    try:
        return _revert(entry_id, user)
    except sqlite3.Error as exc:
        if is_locked_error(exc):
            raise
        logging.getLogger(__name__).exception('Database error reverting organization history')
        raise HTTPException(500, 'Could not restore history', headers={'Cache-Control': 'no-store'}) from exc


def _revert(entry_id: int, user: CurrentUser) -> dict[str, int]:
    headers = {'Cache-Control': 'no-store'}
    with get_db() as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        entry = conn.execute('SELECT * FROM organization_history WHERE id=? AND owner=?', (entry_id, user.user_id or '')).fetchone()
        if not entry:
            raise HTTPException(404, 'History entry not found', headers=headers)
        changes = json.loads(entry['payload'])
        if not _visible(conn, user, changes):
            raise HTTPException(404, 'History entry not available', headers=headers)
        kind, scope = entry['kind'], entry['scope']
        current = snapshot(conn, kind, scope, [change['path'] for change in changes])
        if entry['reverted'] or any(current[c['path']]['values'] != c['after'] or current[c['path']]['revision'] != c['revision'] for c in changes):
            raise HTTPException(409, 'Photos changed since this action; nothing was restored', headers=headers)
        fields = FIELDS[kind]
        for change in changes:
            if kind == 'review' and scope:
                columns = ','.join(fields)
                updates = ','.join(f'{field}=excluded.{field}' for field in fields)
                conn.execute(f'INSERT INTO user_preferences(user_id,photo_path,{columns}) VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,photo_path) DO UPDATE SET {updates}', [scope, change['path'], *change['before']])
            else:
                conn.execute(f"UPDATE photos SET {','.join(f'{field}=?' for field in fields)} WHERE path=?", [*change['before'], change['path']])
        record(conn, user.user_id or '', kind, scope, current)
        conn.execute('UPDATE organization_history SET reverted=1 WHERE id=?', (entry_id,))
        if kind == 'review':
            from api.db_helpers import record_label_origin
            record_label_origin(conn, user.is_agent_request, user.user_id, list(current))
        conn.execute('DELETE FROM stats_cache')
    from api.routers.capture_dates import _after_commit
    _after_commit()
    return {'changed': len(changes)}
