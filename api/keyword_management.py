"""Captured, atomic hierarchy changes. File metadata is never written here."""

import hmac
import time

from fastapi import HTTPException

from api import config, signed_tokens
from api.db_helpers import get_visibility_clause
from api.routers.faces import _writable_photo_paths
from db.keyword_hierarchy import (
    MAX_ASSIGNMENTS, MAX_NODES, HierarchyError, _ancestry, _graph, _path_key, _subtree,
    assign_node, change_node, delete_branch, ensure_path, remove_assignment,
)

_DOMAIN = b'facet-hierarchy-preview-v1\0'
_MAX_PHOTOS = 10000
_MAX_BYTES = 8 * 1024 * 1024


def _json(value):
    return signed_tokens.canonical_json(value)


def _sign(kind, value):
    return signed_tokens.sign(_DOMAIN + kind, value)


def _visible_node(conn, owner, node):
    visible, params = get_visibility_clause(owner)
    found = conn.execute(
        'WITH RECURSIVE branch(id) AS (SELECT id FROM keyword_nodes WHERE id=? UNION '
        'SELECT n.id FROM keyword_nodes n JOIN branch ON n.parent_id=branch.id) '
        'SELECT 1 FROM photo_keyword_nodes a JOIN photos ON photos.path=a.photo_path '
        f'WHERE a.node_id IN (SELECT id FROM branch) AND {visible} LIMIT 1', [node, *params]).fetchone()
    if not found:
        raise HTTPException(404, 'Keyword not found')


def _collect(conn, sql, params, budget):
    rows = []
    cursor = conn.execute(sql, params)
    try:
        while batch := cursor.fetchmany(500):
            values = [dict(row) for row in batch]
            budget[0] += len(_json(values))
            if budget[0] > _MAX_BYTES:
                raise HTTPException(412, 'Hierarchy preview is too large; choose a smaller explicit scope')
            rows.extend(values)
    finally:
        cursor.close()
    return rows


def _snapshot(conn, user, body):
    from api.auth import password_generation
    owner = user.user_id
    graph = _graph(conn)
    for node in graph:
        _ancestry(graph, node)
    request = body.model_dump(exclude={'preview_token'})
    action, node_id = body.action, body.node_id
    before = [node['name'] for node in _ancestry(graph, node_id)] if node_id in graph else None
    structural = action in ('rename', 'move', 'delete_branch')
    if node_id is not None:
        _visible_node(conn, owner, node_id)
    if action == 'move' and body.parent_id is not None:
        _visible_node(conn, owner, body.parent_id)
    branch = _subtree(graph, node_id) if structural else set()
    if structural:
        # Refuse a hidden assignment before collecting any of its private rows.
        visible, params = get_visibility_clause(owner)
        paths = set()
        for start in range(0, len(branch), 500):
            chunk = sorted(branch)[start:start + 500]
            marks = ','.join('?' * len(chunk))
            hidden = conn.execute('SELECT 1 FROM photo_keyword_nodes a JOIN photos ON photos.path=a.photo_path '
                                  f'WHERE a.node_id IN ({marks}) AND NOT ({visible}) LIMIT 1', [*chunk, *params]).fetchone()
            if hidden:
                raise HTTPException(409, 'The complete branch cannot be changed in your writable scope')
            for row in conn.execute(f'SELECT DISTINCT photo_path FROM photo_keyword_nodes WHERE node_id IN ({marks})', chunk):
                paths.add(row[0])
                if len(paths) > _MAX_PHOTOS:
                    raise HTTPException(412, 'Hierarchy management is capped at 10000 photos')
        paths = sorted(paths)
    else:
        paths = sorted(set(body.paths))
    if set(_writable_photo_paths(conn, user, paths)) != set(paths):
        raise HTTPException(409, 'The captured photos are no longer available')
    if not paths:
        raise HTTPException(404, 'No writable assignments found')
    request['paths'] = None if structural else paths

    proposed = {node: dict(value) for node, value in graph.items()}
    after, definition_change = before, False
    if action == 'rename':
        proposed[node_id]['name'] = body.name
        proposed[node_id]['name_key'] = body.name.casefold()
    elif action == 'move':
        proposed[node_id]['parent_id'] = body.parent_id
    if action in ('rename', 'move'):
        changed = proposed[node_id]
        if any(node != node_id and value['parent_id'] == changed['parent_id'] and value['name_key'] == changed['name_key']
               for node, value in proposed.items()):
            raise HierarchyError('The destination already contains that keyword')
        for descendant in branch:
            _ancestry(proposed, descendant)
        after = [node['name'] for node in _ancestry(proposed, node_id)]
        definition_change = proposed[node_id] != graph[node_id]
        if not definition_change:
            raise HTTPException(422, 'Choose a different name or parent')
    elif action == 'delete_branch':
        after, definition_change = None, True
    elif action == 'create_assign':
        after = []
        visible, params = get_visibility_clause(owner)
        known = set()
        for row in conn.execute('SELECT DISTINCT a.node_id FROM photo_keyword_nodes a JOIN photos ON photos.path=a.photo_path '
                                f'WHERE {visible}', params):
            known.update(node['id'] for node in _ancestry(graph, row[0]))
        parent, missing, reserved = None, 0, 0
        for name in body.segments:
            match = next((node for node in graph.values() if node['parent_id'] == parent and node['name_key'] == name.casefold()), None) if missing == 0 else None
            if match:
                parent = match['id']
                after.append(match['name'])
                reserved += int(parent not in known)
            else:
                missing += 1
                reserved += 1
                after.append(name)
        # Reserve all caller-unknown levels uniformly, whether they are physically
        # new or reuse hidden definitions. Capacity must not become a name oracle.
        if len(graph) + reserved > MAX_NODES:
            raise HierarchyError('Keyword vocabulary exceeds the supported node limit')
        node_id = parent if missing == 0 else None
        if node_id in known:
            definition_change = False
        else:
            after = body.segments
            definition_change = None
    budget = [len(_json(graph))]
    assignments, deletions = [], []
    for start in range(0, len(paths), 500):
        chunk = paths[start:start + 500]
        marks = ','.join('?' * len(chunk))
        assignments += _collect(conn, f'SELECT * FROM photo_keyword_nodes WHERE photo_path IN ({marks}) ORDER BY photo_path,node_id', chunk, budget)
        deletions += _collect(conn, f'SELECT * FROM keyword_assignment_deletions WHERE photo_path IN ({marks}) ORDER BY photo_path,path_key', chunk, budget)
    direct = {row['photo_path']: row for row in assignments if row['node_id'] == node_id}
    counts = {}
    for row in assignments:
        counts[row['photo_path']] = counts.get(row['photo_path'], 0) + 1
    new = removed = updated = 0
    if action in ('assign', 'create_assign'):
        new = sum(path not in direct for path in paths)
        if any(path not in direct and counts.get(path, 0) >= MAX_ASSIGNMENTS for path in paths):
            raise HierarchyError('A photo can carry at most 50 directly assigned hierarchy nodes')
        key = _path_key(_ancestry(graph, node_id)) if node_id is not None else None
        intent = {row['photo_path'] for row in deletions if row['node_id'] == node_id or (key is not None and row['path_key'] == key)}
        updated = sum(row['source'] != 'user' or row['photo_path'] in intent for row in direct.values())
    elif action == 'remove':
        removed = len(direct)
    elif action == 'delete_branch':
        removed = sum(row['node_id'] in branch for row in assignments)
    else:
        updated = sum(row['node_id'] in branch for row in assignments)
    actor = (config._FULL_CONFIG.get('users', {}).get(owner) or {}) if owner else {}
    policy = {'owner': owner, 'role': user.role, 'edition': user.is_edition, 'agent': user.agent,
              'trusted': user.trusted_local_editing, 'multi_user': config.is_multi_user_enabled(),
              'directories': config.get_user_directories(owner) if owner else [], 'actor_role': actor.get('role'),
              'viewer_generation': password_generation('password'), 'edition_generation': password_generation('edition_password')}
    state = {'request': request, 'graph': graph, 'assignments': assignments, 'deletions': deletions, 'policy': policy}
    encoded = _json(state)
    if len(encoded) > _MAX_BYTES:
        raise HTTPException(412, 'Hierarchy preview is too large; choose a smaller explicit scope')
    public = {'request': request, 'before_path': before, 'after_path': after, 'paths': paths,
              'new_assignments': new, 'removed_assignments': removed, 'updated_assignments': updated,
              'definition_change': definition_change}
    # Key the private state digest: a client must not dictionary-guess hidden
    # definitions merely because they share a graph with its visible branch.
    return public, _sign(b'state\0', encoded)


def hierarchy_preview(conn, user, body):
    public, digest = _snapshot(conn, user, body)
    expires = int(time.time()) + 600
    payload = _json({'owner': user.user_id, 'digest': digest, 'expires': expires})
    return {**public, 'preview_token': signed_tokens.issue(_DOMAIN + b'token\0', payload),
            'expires_at': expires}


def hierarchy_apply(conn, user, body, *, created_by):
    try:
        claims = signed_tokens.verify(_DOMAIN + b'token\0', body.preview_token)
        if (claims['owner'] != user.user_id or type(claims['expires']) is not int or claims['expires'] <= time.time()
                or not isinstance(claims['digest'], str)):
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, 'Hierarchy preview changed or expired; preview again') from exc
    public, digest = _snapshot(conn, user, body)
    if not hmac.compare_digest(claims['digest'], digest):
        raise HTTPException(409, 'Vocabulary or assignments changed; preview again')
    node_id = body.node_id
    if body.action == 'create_assign':
        node_id = ensure_path(conn, body.segments)
    changed = affected = 0
    if body.action in ('assign', 'create_assign'):
        for path in public['paths']:
            delta = int(assign_node(conn, path, node_id, created_by=created_by))
            changed += delta
            affected += delta
    elif body.action == 'remove':
        for path in public['paths']:
            delta = int(remove_assignment(conn, path, node_id))
            changed += delta
            affected += delta
    elif body.action == 'delete_branch':
        delete_branch(conn, node_id, writable_paths=set(public['paths']))
        changed = public['removed_assignments']
        affected = len(public['paths'])
        node_id = None
    else:
        options = {'name': body.name} if body.action == 'rename' else {'parent_id': body.parent_id}
        change_node(conn, node_id, writable_paths=set(public['paths']), created_by=created_by, **options)
        changed = public['updated_assignments']
        affected = len(public['paths'])
    return {'success': True, 'node_id': node_id, 'target_photos': len(public['paths']),
            'affected_photos': affected, 'changed_assignments': changed}
