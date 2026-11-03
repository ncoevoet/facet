"""Private logical review receipts; caller owns authorization and transaction.

Uses the existing private organization_history table (excluded from viewer
exports). Restores sparse authority, never physical photo/preference labels.
API/list/UI integration is separate from this storage layer.
"""
import json

from db import logical_review as review
from db.logical_assets import AssetConflict, _members
from db.organization_history import MAX_BYTES, MAX_ENTRIES, MAX_PHOTOS, encode, snapshot, store_parts, FIELDS as PHYSICAL_FIELDS

FIELDS = ('star_rating', 'is_favorite', 'is_rejected', 'is_kept')


def capture(conn, asset_id, owner, file_labels):
    state = review.read(conn, asset_id, owner, file_labels)
    group = conn.execute('SELECT revision FROM logical_assets WHERE id=?', (asset_id,)).fetchone()
    members = [row[0] for row in conn.execute(
        'SELECT photo_path FROM logical_asset_members WHERE asset_id=? ORDER BY position', (asset_id,))]
    if group is None or not members or not set(members) <= file_labels.keys():
        raise AssetConflict('Logical review unavailable')
    overrides = [list(row) for row in conn.execute(
        'SELECT field,value,origin FROM logical_review_fields WHERE asset_id=? AND owner=? ORDER BY field', (asset_id, owner))]
    return dict(asset_id=asset_id, owner=owner, path=members[0], group_revision=group[0],
                revision=state['revision'], input_token=state['input_token'],
                values=[state['values'][field] for field in FIELDS], overrides=overrides)


def record(conn, actor, owner, before, after, *, physical_before=None):
    if not conn.in_transaction or not isinstance(actor, str) or not isinstance(owner, str):
        raise AssetConflict('A scoped history transaction is required')
    changes = []
    for key, old in before.items():
        new = after[key]
        if old['owner'] != owner or new['owner'] != owner or old['asset_id'] != key or new['asset_id'] != key:
            raise AssetConflict('Logical history scope changed')
        if old['revision'] == new['revision'] and old['overrides'] == new['overrides']:
            continue
        changes.append(dict(path=new['path'], asset_id=key, before=old['values'], after=new['values'],
                            override_before=old['overrides'], override_after=new['overrides'],
                            group_revision=new['group_revision'], revision=new['revision'], input_token=new['input_token']))
    physical_before = physical_before or {}
    physical_after = snapshot(conn, 'review', owner, list(physical_before))
    for path, old in physical_before.items():
        new = physical_after.get(path)
        if new is None:
            raise AssetConflict('Physical review disappeared')
        if old['values'] != new['values']:
            changes.append(dict(path=path, before=old['values'], after=new['values'], revision=new['revision']))
    if not changes:
        return []
    parts, part, size = [], [], 2
    for change in changes:
        length = len(encode(change).encode('utf-8'))
        if length + 2 > MAX_BYTES:
            raise AssetConflict('Logical history entry is too large')
        if part and (len(part) >= MAX_PHOTOS or size + length + 1 > MAX_BYTES):
            parts.append(part)
            part, size = [], 2
        size += length + bool(part)
        part.append(change)
    parts.append(part)
    with review._transaction(conn):
        return store_parts(conn, actor, 'logical_review', owner, parts, max_entries=MAX_ENTRIES)


def restore(conn, actor, owner, entry_id, file_labels, *, visibility_sql, visibility_params=()):
    """Preflight every member/clock/input before restoring one whole receipt."""
    if not conn.in_transaction:
        raise AssetConflict('A history write transaction is required')
    entry = conn.execute('SELECT payload,reverted FROM organization_history '
                         "WHERE id=? AND owner=? AND scope=? AND kind='logical_review'", (entry_id, actor, owner)).fetchone()
    if not entry or entry[1]:
        raise AssetConflict('Logical history entry unavailable')
    changes = json.loads(entry[0])
    current = {}
    physical = [change for change in changes if 'asset_id' not in change]
    paths = [change['path'] for change in physical]
    physical_current = snapshot(conn, 'review', owner, paths)
    for change in physical:
        now = physical_current.get(change['path'])
        visible = conn.execute(f'SELECT 1 FROM photos WHERE path=? AND ({visibility_sql})',
                               [change['path'], *visibility_params]).fetchone()
        grouped = conn.execute('SELECT 1 FROM logical_asset_members WHERE photo_path=?', [change['path']]).fetchone()
        if (not visible or grouped or now is None or now['values'] != change['after']
                or now['revision'] != change['revision']):
            raise AssetConflict('Physical review changed; nothing was restored')
    for change in changes:
        if 'asset_id' not in change:
            continue
        key = change['asset_id']
        _members(conn, key, change['group_revision'], visibility_sql, visibility_params)
        now = capture(conn, key, owner, file_labels)
        if (now['revision'] != change['revision'] or now['input_token'] != change['input_token']
                or now['overrides'] != change['override_after']):
            raise AssetConflict('Logical review changed; nothing was restored')
        current[key] = now
    with review._transaction(conn):
        for change in changes:
            if 'asset_id' not in change:
                continue
            key = change['asset_id']
            now = current[key]
            review.reset_fields(conn, key, owner, now['group_revision'], now['revision'], list(review.FIELDS),
                                visibility_sql=visibility_sql, visibility_params=visibility_params,
                                file_labels=file_labels, input_token=now['input_token'])
            conn.executemany('INSERT INTO logical_review_fields VALUES (?,?,?,?,?)',
                             [(key, owner, field, value, origin) for field, value, origin in change['override_before']])
        fields = PHYSICAL_FIELDS['review']
        for change in physical:
            if owner:
                marks = ','.join('?' for _ in range(2 + len(fields)))
                updates = ','.join(f'{field}=excluded.{field}' for field in fields)
                conn.execute(f'INSERT INTO user_preferences(user_id,photo_path,{",".join(fields)}) VALUES ({marks}) '
                             f'ON CONFLICT(user_id,photo_path) DO UPDATE SET {updates}',
                             [owner, change['path'], *change['before']])
            else:
                conn.execute(f'UPDATE photos SET {",".join(f"{field}=?" for field in fields)} WHERE path=?',
                             [*change['before'], change['path']])
        restored = {key: capture(conn, key, owner, file_labels) for key in current}
        record(conn, actor, owner, current, restored, physical_before=physical_current)
        conn.execute('UPDATE organization_history SET reverted=1 WHERE id=?', (entry_id,))
    return len(changes)
