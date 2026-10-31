"""Bounded, owner-private regroup previews and caller-transaction mutations."""
import hashlib
import json
import re
import sqlite3
import uuid

from db import organization_history as history, stacks


def _load_membership(conn, owner, selected_paths):
    """Map each selected, already-stacked path to its stack id; refuse orphan members."""
    from api.db_helpers import select_in_chunks
    membership = {}
    for path, stack_id in select_in_chunks(
            conn, '''SELECT m.photo_path,s.id
            FROM photo_stack_members m LEFT JOIN photo_stacks s ON s.id=m.stack_id AND s.owner=m.owner
            WHERE m.owner=? AND m.photo_path IN ({placeholders})''',
            selected_paths, before=[owner], chunk=stacks.IN_CHUNK):
        if stack_id is None:
            raise stacks.StackError()
        membership[path] = stack_id
    return membership


def _authorize_sources(conn, source_ids, visibility_sql, visibility_params):
    """Total the sources' members, refusing unless every one is visible.

    Source IDs came from this owner's parent stacks, in this same transaction.
    IDs are globally unique; matching parent/member owners retains that authorization
    without rebinding owner, leaving one ID slot even with 998 visibility bindings.
    """
    from api.db_helpers import select_in_chunks
    total = 0
    for count, permitted in select_in_chunks(
            conn, f'''SELECT COUNT(*),
            COALESCE(SUM(CASE WHEN photos.path IS NOT NULL AND ({visibility_sql}) THEN 1 ELSE 0 END),0)
            FROM photo_stack_members m JOIN photo_stacks s ON s.id=m.stack_id AND s.owner=m.owner
            LEFT JOIN photos ON photos.path=m.photo_path
            WHERE s.id IN ({{placeholders}})''',
            source_ids, before=visibility_params,
            chunk=stacks.visibility_chunk_size(len(visibility_params))):
        if count != permitted:
            raise stacks.StackError()
        total += count
    return total


def _load_sources(conn, owner, source_ids):
    """Load the sources' ordered members, bounded by the global member limit."""
    sources = {}
    member_count = 0
    for start in range(0, len(source_ids), stacks.IN_CHUNK):
        chunk = source_ids[start:start + stacks.IN_CHUNK]
        marks = ','.join('?' for _ in chunk)
        rows = conn.execute(f'''SELECT s.id,s.revision,s.cover_path,m.photo_path,m.position
            FROM photo_stacks s JOIN photo_stack_members m ON m.stack_id=s.id AND m.owner=s.owner
            WHERE s.owner=? AND s.id IN ({marks}) ORDER BY s.id,m.position LIMIT ?''',
            [owner, *chunk, stacks.MAX_MEMBERS + 1 - member_count])
        for stack_id, revision, cover, path, position in rows:
            source = sources.setdefault(stack_id, dict(id=stack_id, revision=revision, cover_path=cover,
                                                       members=[], editable=True))
            source['members'].append(dict(path=path, position=position))
            member_count += 1
        if member_count > stacks.MAX_MEMBERS:
            raise stacks.StackError('Regrouping affects at most 1000 photos', 422)
    return sources


def _affected_paths(selected_paths, membership, sources):
    """Selected photos, each stacked one expanded once to its whole source."""
    affected = []
    visited = set()
    for path in selected_paths:
        stack_id = membership.get(path)
        if stack_id is None:
            affected.append(path)
        elif stack_id not in visited:
            affected.extend(m['path'] for m in sources[stack_id]['members'])
            visited.add(stack_id)
    return affected


def _expected_state(owner, selected_paths, mode, source_stacks, before):
    canonical = dict(owner=owner, selected_paths=selected_paths, mode=mode, sources=source_stacks, state=before)
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _resolve(conn, owner, selected_paths, mode, visibility_sql, visibility_params):
    stacks.transaction(conn)
    stacks.check_paths(selected_paths, 2)
    if mode not in ('combine', 'selected'):
        raise stacks.StackError('Unknown regroup mode', 422)
    if stacks.visible_paths(conn, selected_paths, visibility_sql, visibility_params) != set(selected_paths):
        raise stacks.StackError()
    membership = _load_membership(conn, owner, selected_paths)
    source_ids = list(dict.fromkeys(membership[p] for p in selected_paths if p in membership))
    unstacked = [p for p in selected_paths if p not in membership]
    # Check full authorization before revealing even a limit refusal. Counts
    # keep oversized source sets bounded without loading their member paths.
    total_members = len(unstacked) + _authorize_sources(conn, source_ids, visibility_sql, visibility_params)
    if total_members > stacks.MAX_MEMBERS:
        raise stacks.StackError('Regrouping affects at most 1000 photos', 422)
    sources = _load_sources(conn, owner, source_ids)
    if set(sources) != set(source_ids):
        raise stacks.StackError()
    affected = _affected_paths(selected_paths, membership, sources)
    if stacks.visible_paths(conn, affected, visibility_sql, visibility_params) != set(affected):
        raise stacks.StackError()
    source_stacks = [sources[stack_id] for stack_id in source_ids]
    before = history.snapshot(conn, 'stack', owner, affected)
    expected_state = _expected_state(owner, selected_paths, mode, source_stacks, before)
    paths = affected.copy() if mode == 'combine' else selected_paths.copy()
    cover = (source_stacks[0]['cover_path'] if len(source_stacks) == 1
             and source_stacks[0]['cover_path'] in paths else selected_paths[0])
    return dict(selected_paths=selected_paths.copy(), mode=mode, paths=paths, cover_path=cover,
                source_stacks=source_stacks, unstacked_paths=unstacked,
                affected_paths=affected, expected_state=expected_state), before


def _previews(conn, sources):
    from db.preview_versions import attach_preview_versions
    attach_preview_versions(conn, [member for source in sources for member in source['members']])


def preview_regroup(conn: sqlite3.Connection, owner: str, selected_paths: list[str], mode: str, *,
                    visibility_sql: str = '1=1', visibility_params: tuple | list = ()) -> dict:
    """Read a membership snapshot without disclosing partially visible sources."""
    result, _ = _resolve(conn, owner, selected_paths, mode, visibility_sql, visibility_params)
    _previews(conn, result['source_stacks'])
    return result


def apply_regroup(conn: sqlite3.Connection, owner: str, selected_paths: list[str], mode: str,
                  paths: list[str], cover_path: str, expected_state: str, *,
                  visibility_sql: str = '1=1', visibility_params: tuple | list = ()) -> dict:
    """Preflight every source and whole Undo payload before changing membership.

    The caller owns the transaction and must roll it back on any exception, as
    with the strict stack helpers. No precondition refusal performs a write.
    """
    stacks.transaction(conn)
    stacks.check_paths(paths, 2)
    if cover_path not in paths:
        raise stacks.StackError('Cover must be a member', 422)
    if not isinstance(expected_state, str) or re.fullmatch('[0-9a-fA-F]{64}', expected_state) is None:
        raise stacks.StackError('Invalid regroup snapshot', 422)
    preview, before = _resolve(conn, owner, selected_paths, mode, visibility_sql, visibility_params)
    if preview['expected_state'] != expected_state.lower():
        raise stacks.StackError('Stack membership changed; refresh the preview')
    if not set(paths).issubset(preview['paths']):
        raise stacks.StackError('Destination must contain only previewed photos', 422)
    # Validate the complete preview above, but mutate only sources contributing
    # to the final destination. Wholly excluded groups keep their own revisions
    # and must not become dependencies of this operation's whole-stack Undo.
    chosen = set(paths)
    sources = [source for source in preview['source_stacks']
               if any(member['path'] in chosen for member in source['members'])]
    touched = chosen | {member['path'] for source in sources for member in source['members']}
    affected = [path for path in preview['affected_paths'] if path in touched]
    before = {path: before[path] for path in affected}
    if (len(sources) == 1 and paths == [m['path'] for m in sources[0]['members']]
            and cover_path == sources[0]['cover_path']):
        _previews(conn, sources)
        return dict(stack=sources[0], undo=None, affected_paths=affected, changed=False)
    residuals = [(source, [m['path'] for m in source['members'] if m['path'] not in chosen])
                 for source in sources]
    destination = sources[0]['id'] if len(sources) == 1 and len(residuals[0][1]) < 2 else str(uuid.uuid4())
    groups = [(source['id'], members,
               source['cover_path'] if source['cover_path'] in members else members[0])
              for source, members in residuals if len(members) >= 2]
    groups.append((destination, paths, cover_path))
    # Use the same shape/encoding as history.record, including unchanged residual
    # members. A whole stack edit cannot be split into independently undone parts.
    revision = conn.execute('SELECT revision+1 FROM organization_clock WHERE id=1').fetchone()[0]
    after: dict[str, list[str | int]] = {p: [] for p in affected}
    for stack_id, members, cover in groups:
        after.update({path: [stack_id, cover, position] for position, path in enumerate(members)})
    changes = [dict(path=path, before=before[path]['values'], after=after[path], revision=revision)
               for path in before]
    if len(history.encode(changes).encode()) > history.MAX_BYTES:
        raise ValueError('Organization history entry is too large')
    revision = stacks.stamp(conn, owner, affected)
    # Clear all memberships first so no source's UNIQUE(owner,photo_path)
    # constraint can conflict with the destination or a retained residual.
    for source in sources:
        conn.execute('DELETE FROM photo_stack_members WHERE stack_id=? AND owner=?', (source['id'], owner))
    retained_ids = {group[0] for group in groups}
    for source in sources:
        if source['id'] not in retained_ids:
            stacks.write(conn, owner, source['id'], [], None, revision)
    for stack_id, members, cover in groups:
        stacks.write(conn, owner, stack_id, members, cover, revision)
    result = stacks.finish(conn, owner, before, destination)
    return dict(**result, affected_paths=affected, changed=True)
