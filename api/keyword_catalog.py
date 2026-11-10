"""Flat keyword identities: read discovery and atomic explicit assignment edits.

A slash is literal data. This module never invents parent tags or modifies AI
labels, photos, files, imported sidecars or another account's hidden assignments.
"""

import hashlib
import hmac
import time

from fastapi import HTTPException

from api import signed_tokens
from api.db_helpers import get_visibility_clause
from db.manual_tags import ManualTagError, escape_like, is_ai_tag, normalize_manual_tag

_DOMAIN = b'facet-keyword-assignment-preview-v1\0'
_MAX_PHOTOS = 10000
_MAX_BYTES = 8 * 1024 * 1024


def _json(value):
    return signed_tokens.canonical_json(value)


def _normalized(value):
    try:
        return normalize_manual_tag(value)
    except ManualTagError as exc:
        raise HTTPException(422, str(exc)) from exc


def keyword_catalog(conn, owner, search, after, limit):
    query = _normalized(search) if search.strip() else ''
    vis, values = get_visibility_clause(owner)
    where = f'{vis} AND m.tag LIKE ? ESCAPE \'\\\''
    params = [*values, '%' + escape_like(query) + '%']
    total = conn.execute(f'SELECT COUNT(DISTINCT m.tag) FROM photo_manual_tags m '
                         f'JOIN photos ON photos.path=m.photo_path WHERE {where}', params).fetchone()[0]
    rows = conn.execute(
        'SELECT m.tag, COUNT(*) AS count, SUM(CASE WHEN m.source=\'user\' THEN 1 ELSE 0 END) AS typed, '
        'SUM(CASE WHEN m.source=\'xmp\' THEN 1 ELSE 0 END) AS imported, '
        'SUM(m.source IS NULL OR m.source NOT IN (\'user\',\'xmp\')) AS unrecorded '
        f'FROM photo_manual_tags m JOIN photos ON photos.path=m.photo_path WHERE {where} '
        'AND m.tag > ? GROUP BY m.tag ORDER BY m.tag LIMIT ?', [*params, after, limit + 1]).fetchall()
    items = [dict(row) for row in rows[:limit]]
    return {'items': items, 'total': total, 'next_after': items[-1]['tag'] if len(rows) > limit else None}


def _snapshot(conn, owner, body):
    source = _normalized(body.source)
    target = _normalized(body.target) if body.target is not None else None
    if target == source:
        raise HTTPException(422, 'Choose a different keyword')
    vis, params = get_visibility_clause(owner)
    rows = conn.execute(
        'SELECT m.photo_path, m.source, m.created_by, m.created_at, photos.tags, '
        'd.tag AS destination, d.source AS destination_source, d.created_by AS destination_by, '
        'd.created_at AS destination_at FROM photo_manual_tags m '
        'JOIN photos ON photos.path=m.photo_path LEFT JOIN photo_manual_tags d '
        'ON d.photo_path=m.photo_path AND d.tag=? '
        f'WHERE m.tag=? AND {vis} ORDER BY m.photo_path LIMIT ?',
        [target, source, *params, _MAX_PHOTOS + 1]).fetchall()
    if len(rows) > _MAX_PHOTOS:
        raise HTTPException(412, 'Keyword management is capped at 10000 photos; use a captured photo selection instead')
    if not rows:
        raise HTTPException(404, 'No visible manual assignments found')
    snapshot = {'owner': owner, 'source': source, 'target': target, 'rows': [dict(row) for row in rows]}
    encoded = _json(snapshot)
    if len(encoded) > _MAX_BYTES:
        raise HTTPException(412, 'Keyword preview is too large; use a smaller captured selection')
    return snapshot, hashlib.sha256(encoded).hexdigest()


def keyword_preview(conn, owner, body):
    snapshot, digest = _snapshot(conn, owner, body)
    expires = int(time.time()) + 600
    payload = _json({'owner': owner, 'digest': digest, 'expires': expires})
    target = snapshot['target']
    merged = sum(bool(row['destination']) for row in snapshot['rows']) if target else 0
    ai_matches = sum(not row['destination'] and is_ai_tag(row['tags'], target)
                     for row in snapshot['rows']) if target else 0
    return {'source': snapshot['source'], 'target': target,
            'paths': [row['photo_path'] for row in snapshot['rows']],
            'renamed': len(snapshot['rows']) - merged - ai_matches if target else 0,
            'merged': merged, 'ai_matches': ai_matches, 'removed': len(snapshot['rows']) if target is None else 0,
            'preview_token': signed_tokens.issue(_DOMAIN, payload),
            'expires_at': expires}


def apply_keyword_change(conn, owner, body, *, created_by):
    try:
        claims = signed_tokens.verify(_DOMAIN, body.preview_token)
        if claims['owner'] != owner or claims['expires'] <= time.time():
            raise ValueError('changed or expired preview')
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, 'Keyword preview changed or expired; preview again') from exc
    snapshot, digest = _snapshot(conn, owner, body)
    if not hmac.compare_digest(claims.get('digest', ''), digest):
        raise HTTPException(409, 'Keyword assignments changed; preview again')
    source, target = snapshot['source'], snapshot['target']
    for row in snapshot['rows']:
        if target is None or row['destination'] or is_ai_tag(row['tags'], target):
            conn.execute('DELETE FROM photo_manual_tags WHERE photo_path=? AND tag=?', (row['photo_path'], source))
        else:
            conn.execute('UPDATE photo_manual_tags SET tag=?,source=\'user\',created_by=?,created_at=datetime(\'now\') '
                         'WHERE photo_path=? AND tag=?', (target, created_by, row['photo_path'], source))
    return {'source': source, 'target': target, 'changed': len(snapshot['rows'])}
