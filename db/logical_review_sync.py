"""Logical-review viewer sync: imported values never become viewer edits.

Per-field local clocks protect explicit same-value edits and resets. Retired
review records remain private to their database and are omitted from full copies.
"""
import hashlib
import json

from db.logical_review import init_schema

_REVIEW_TABLES = {'logical_review_fields', 'logical_review_field_versions', 'logical_review_seeds'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def init_receipts(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_review_imports (
        asset_id TEXT NOT NULL, owner TEXT NOT NULL, field TEXT NOT NULL,
        signature TEXT NOT NULL, local_revision INTEGER NOT NULL,
        PRIMARY KEY(asset_id,owner,field))''')


def _snapshot(conn, schema):
    if schema not in ('main', 'src'):
        raise ValueError('Unsupported catalog schema')
    tables = {row[0] for row in conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table'")}
    if not _REVIEW_TABLES <= tables:
        return None
    active = {row[0] for row in conn.execute(f'SELECT id FROM {schema}.logical_assets')}
    fields = {(a, o, f): (v, origin) for a, o, f, v, origin in conn.execute(
        f'SELECT r.asset_id,r.owner,r.field,r.value,r.origin FROM {schema}.logical_review_fields r '
        f'JOIN {schema}.logical_assets a ON a.id=r.asset_id')}
    versions = {(a, o, f): v for a, o, f, v in conn.execute(
        f'SELECT r.asset_id,r.owner,r.field,r.revision FROM {schema}.logical_review_field_versions r '
        f'JOIN {schema}.logical_assets a ON a.id=r.asset_id')}
    seeds = dict(conn.execute(f'SELECT r.asset_id,r.photo_path FROM {schema}.logical_review_seeds r '
                              f'JOIN {schema}.logical_assets a ON a.id=r.asset_id'))
    return active, fields, versions, seeds


def _baseline(conn):
    return {(a, o, f): (signature, revision) for a, o, f, signature, revision in conn.execute(
        'SELECT r.asset_id,r.owner,r.field,r.signature,r.local_revision FROM logical_review_imports r '
        'JOIN logical_assets a ON a.id=r.asset_id')}


def _unchanged(key, fields, versions, baseline):
    prior = baseline.get(key)
    if prior is None:
        return key not in fields and versions.get(key, 0) == 0
    return prior == (_digest(fields.get(key)), versions.get(key, 0))


def capture_imports(conn):
    """Initialize this viewer's receipts, never copy the source's own receipts."""
    init_receipts(conn)
    conn.execute('DELETE FROM logical_review_imports')
    state = _snapshot(conn, 'main')
    if state is None:
        return
    active, fields, versions, _ = state
    for key in fields.keys() | versions.keys():
        if key[0] in active:
            conn.execute('INSERT INTO logical_review_imports VALUES (?,?,?,?,?)',
                         (*key, _digest(fields.get(key)), versions.get(key, 0)))


def omit_retired(conn):
    """Full-copy boundary: active catalog data ships; private retired history does not."""
    from db.logical_assets import init_schema as init_assets
    init_assets(conn)
    init_schema(conn)
    for table in ('logical_review_seeds', 'logical_review_fields', 'logical_review_versions', 'logical_review_field_versions'):
        conn.execute(f'DELETE FROM {table} WHERE asset_id NOT IN (SELECT id FROM logical_assets)')


def protected_retirements(conn, source_ids):
    """Do not retire an active viewer group carrying local review values or resets."""
    state = _snapshot(conn, 'main')
    if state is None:
        return set()
    init_receipts(conn)
    active, fields, versions, _ = state
    baseline = _baseline(conn)
    return {key[0] for key in fields.keys() | versions.keys() if key[0] in active and key[0] not in source_ids
            and not _unchanged(key, fields, versions, baseline)}


def sync_imports(conn, imported_assets, plan):
    """Merge active source fields independently; caller owns commit and group sync."""
    if not conn.in_transaction:
        conn.execute('BEGIN')
    source = _snapshot(conn, 'src')
    if source is None:
        return
    init_schema(conn)
    init_receipts(conn)
    active, fields, versions, _ = _snapshot(conn, 'main')
    source_active, source_fields, source_versions, source_seeds = source
    baseline = _baseline(conn)
    conn.execute('SAVEPOINT logical_review_sync')
    try:
        for asset_id in imported_assets & active:
            if asset_id not in source_active:
                continue
            source_path = source_seeds.get(asset_id)
            if source_path is not None and not conn.execute(
                    'SELECT 1 FROM logical_asset_members WHERE asset_id=? AND photo_path=?',
                    (asset_id, source_path)).fetchone():
                source_path = None
            existing = conn.execute('SELECT photo_path FROM logical_review_seeds WHERE asset_id=?', (asset_id,)).fetchone()
            if existing is None:
                conn.execute('INSERT INTO logical_review_seeds VALUES (?,?)', (asset_id, source_path))
            elif existing[0] != source_path and existing[0] is None and source_path is not None:
                # Transfer only a known source-file relink, not a primary switch
                # or an older scanner's first adoption of review authority.
                prior = plan.review_seeds.get(asset_id)
                old_paths = {path for path, _ in plan.before.get(asset_id, (None, 0, []))[2]}
                if (prior is not None and source_path not in old_paths
                        and not conn.execute('SELECT 1 FROM photos WHERE path=?', (prior,)).fetchone()):
                    conn.execute('UPDATE logical_review_seeds SET photo_path=? WHERE asset_id=?', (source_path, asset_id))
        for key in source_fields.keys() | source_versions.keys() | baseline.keys():
            if key[0] not in active or key[0] not in source_active or not _unchanged(key, fields, versions, baseline):
                continue
            value = source_fields.get(key)
            if value != fields.get(key):
                if value is None:
                    conn.execute('DELETE FROM logical_review_fields WHERE asset_id=? AND owner=? AND field=?', key)
                else:
                    conn.execute('INSERT INTO logical_review_fields VALUES (?,?,?,?,?) '
                                 'ON CONFLICT(asset_id,owner,field) DO UPDATE SET value=excluded.value,origin=excluded.origin',
                                 (*key, *value))
            row = conn.execute('SELECT revision FROM logical_review_field_versions WHERE asset_id=? AND owner=? AND field=?', key).fetchone()
            conn.execute('INSERT INTO logical_review_imports VALUES (?,?,?,?,?) '
                         'ON CONFLICT(asset_id,owner,field) DO UPDATE SET signature=excluded.signature,local_revision=excluded.local_revision',
                         (*key, _digest(value), row[0] if row else 0))
    except BaseException:
        conn.execute('ROLLBACK TO logical_review_sync')
        conn.execute('RELEASE logical_review_sync')
        raise
    else:
        conn.execute('RELEASE logical_review_sync')
