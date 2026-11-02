"""Viewer-copy authority for catalog logical assets, separate from private stacks.

Imported signatures are local synchronization receipts. They are never independent
viewer edits. A changed or dissolved viewer group wins over later source exports.
"""
from dataclasses import dataclass
import hashlib
import json
import sqlite3

from db.logical_assets import init_schema


def _snapshot(conn: sqlite3.Connection, schema: str):
    if schema not in ('main', 'src'):
        raise ValueError('Unsupported catalog schema')
    tables = {row[0] for row in conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table'")}
    if not {'logical_assets', 'logical_asset_members'} <= tables:
        return None
    members: dict[str, list[tuple[str, int]]] = {}
    for asset_id, path, position in conn.execute(
            f'SELECT asset_id,photo_path,position FROM {schema}.logical_asset_members ORDER BY asset_id,position'):
        members.setdefault(asset_id, []).append((path, position))
    return {asset_id: (primary, revision, members.get(asset_id, []))
            for asset_id, primary, revision in conn.execute(
                f'SELECT id,primary_path,revision FROM {schema}.logical_assets')}


def _signature(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def init_receipts(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_asset_imports (
        asset_id TEXT PRIMARY KEY, signature TEXT NOT NULL, members_json TEXT NOT NULL)''')


def capture_imports(conn):
    """After a full copy, establish imported state without retaining source receipts."""
    init_receipts(conn)
    conn.execute('DELETE FROM logical_asset_imports')
    for asset_id, value in (_snapshot(conn, 'main') or {}).items():
        conn.execute('INSERT INTO logical_asset_imports VALUES (?,?,?)',
                     (asset_id, _signature(value), json.dumps([path for path, _ in value[2]], ensure_ascii=False)))


@dataclass
class AssetSyncPlan:
    preserved: set[str]
    before: dict
    review_seeds: dict


def prepare_sync(conn):
    """Capture viewer edits before mechanical photo deletion can change groups."""
    if not conn.in_transaction:
        conn.execute('BEGIN')
    current = _snapshot(conn, 'main') or {}
    init_receipts(conn)
    baseline = dict(conn.execute('SELECT asset_id,signature FROM logical_asset_imports'))
    preserved = {asset_id for asset_id in set(current) | set(baseline)
                 if asset_id not in baseline or asset_id not in current
                 or _signature(current[asset_id]) != baseline[asset_id]}
    has_seeds = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='logical_review_seeds'").fetchone()
    seeds = dict(conn.execute('SELECT s.asset_id,s.photo_path FROM logical_review_seeds s '
                              'JOIN logical_assets a ON a.id=s.asset_id')) if has_seeds else {}
    return AssetSyncPlan(preserved, current, seeds)


def sync_imports(conn, preserved=None):
    """Merge an attached source after photo synchronization; caller owns commit.

    Group replacement is all-or-nothing. Local membership/primary changes and
    local dissolution tombstones are preserved, including member collisions.
    Older sources without logical-asset tables leave viewer choices untouched.
    """
    if not conn.in_transaction:
        conn.execute('BEGIN')
    source = _snapshot(conn, 'src')
    if source is None:
        return set()
    init_schema(conn)
    init_receipts(conn)
    current = _snapshot(conn, 'main')
    baseline = dict(conn.execute('SELECT asset_id,signature FROM logical_asset_imports'))
    conn.execute('SAVEPOINT logical_asset_sync')
    imported_assets: set[str] = set()
    try:
        # Only unchanged imported groups can be replaced or removed.
        plan = prepare_sync(conn) if preserved is None else preserved
        protected = set(plan.preserved)
        from db.logical_review_sync import protected_retirements
        protected.update(protected_retirements(conn, set(source)))
        available = {row[0] for row in conn.execute('SELECT path FROM photos')}
        # The exporter commits photo batches. Protect edits made during those
        # batches too; only predict the effects of mechanical deleted-photo cleanup.
        for asset_id, (primary, revision, members) in plan.before.items():
            remaining = [(path, position) for path, position in members if path in available]
            expected = None if len(remaining) < 1 else (
                primary if primary in {path for path, _ in remaining} else None,
                revision + len(members) - len(remaining), remaining)
            if current.get(asset_id) != expected:
                protected.add(asset_id)
        protected.update(set(current) - set(plan.before))
        replaceable = set(baseline) - protected
        occupied = {path for asset_id in protected if asset_id in current for path, _ in current[asset_id][2]}
        # Dissolution is a local choice about files, not only a source UUID.
        # A source regroup under a new ID must not resurrect those same files.
        for asset_id, members_json in conn.execute('SELECT asset_id,members_json FROM logical_asset_imports'):
            if asset_id in protected and asset_id not in current:
                occupied.update(json.loads(members_json))
        for asset_id in sorted(set(source) | replaceable):
            value = source.get(asset_id)
            if asset_id in protected:
                continue
            if value is not None:
                primary, revision, members = value
                paths = [path for path, _ in members]
                if (len(paths) < 1 or len(paths) != len(set(paths))
                        or primary is not None and primary not in paths
                        or not set(paths) <= available or set(paths) & occupied):
                    continue
                # A member can move between source groups. Remove its unchanged
                # imported former group before installing the new group.
                blockers = {row[0] for path in paths for row in conn.execute(
                    'SELECT asset_id FROM logical_asset_members WHERE photo_path=? AND asset_id!=?', (path, asset_id))}
                if not blockers <= replaceable:
                    continue
                for blocker in blockers:
                    conn.execute('DELETE FROM logical_assets WHERE id=?', (blocker,))
                    conn.execute('DELETE FROM logical_asset_imports WHERE asset_id=?', (blocker,))
            conn.execute('DELETE FROM logical_assets WHERE id=?', (asset_id,))
            conn.execute('DELETE FROM logical_asset_imports WHERE asset_id=?', (asset_id,))
            if value is not None:
                imported_assets.add(asset_id)
                conn.execute('INSERT INTO logical_assets VALUES (?,NULL,?)', (asset_id, revision))
                conn.executemany('INSERT INTO logical_asset_members VALUES (?,?,?)',
                                 [(asset_id, path, position) for path, position in members])
                conn.execute('UPDATE logical_assets SET primary_path=? WHERE id=?', (primary, asset_id))
                conn.execute('INSERT INTO logical_asset_imports VALUES (?,?,?)',
                     (asset_id, _signature(value), json.dumps([path for path, _ in value[2]], ensure_ascii=False)))
    except BaseException:
        conn.execute('ROLLBACK TO logical_asset_sync')
        conn.execute('RELEASE logical_asset_sync')
        raise
    else:
        conn.execute('RELEASE logical_asset_sync')

    return imported_assets
