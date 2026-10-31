"""Offline, explicit path relinking. Preview first; never move or guess files.

Run ``python database.py --relink-photos --help``. This is an operator maintenance command,
not an authenticated API. Stop scanners/viewers and external file editors first.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import sys
import unicodedata

from db.connection import load_sqlite_vec
from db.maintenance import evict_derived_stats_cache, is_path_deleted
from db.stats_cache import invalidate_metric_ranges

MAX_PHOTOS = 100
MAX_FILES = 300
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_PLAN_BYTES = 2 * 1024 * 1024
_PLAIN_REFS = {
    ('albums', 'cover_photo_path'), ('album_photos', 'photo_path'),
    ('album_client_picks', 'photo_path'), ('rating_provenance', 'photo_path'),
    ('face_reextract_snapshot', 'photo_path'),
    ('photo_stacks', 'cover_path'), ('photo_stack_members', 'photo_path'),
    ('stack_suggestion_dismissals', 'photo_path'),
}
_NON_ASSET_PATHS = {
    ('photos', 'path'), ('photos_fts', 'path'), ('scan_failures', 'path'),
}

# Organization history owns these tables outside db.schema's column catalog.
# Historical payload JSON and the global revision clock are not asset links.
# Keep the exact column inventory so future additions still require review.
_AUXILIARY_COLUMNS = {
    'photo_stacks': {'id', 'owner', 'cover_path', 'revision'},
    'immich_stack_links': {'scope', 'local_stack_id', 'remote_stack_id', 'local_fingerprint', 'remote_fingerprint'},
    'immich_stack_send_claims': {'admission_scope', 'asset_id', 'operation_id'},
    'immich_stack_receipts': {'scope', 'admission_scope', 'operation_id', 'status', 'local_stack_id', 'remote_stack_id', 'asset_ids', 'updated_at'},
    'photo_stack_members': {'stack_id', 'owner', 'photo_path', 'position'},
    'stack_suggestion_dismissals': {'owner', 'key', 'kind', 'size', 'photo_path'},
    'organization_clock': {'id', 'revision'},
    'organization_history': {'id', 'owner', 'kind', 'scope', 'created_at', 'payload', 'part', 'parts', 'reverted'},
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _row_digest(row):
    return _digest([{'blob_sha256': hashlib.sha256(v).hexdigest()} if isinstance(v, bytes) else v
                    for v in row])


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _canonical(path):
    if not isinstance(path, str) or not os.path.isabs(path) or '\x00' in path:
        raise ValueError('Relink paths must be absolute native paths')
    if path != os.path.realpath(path):
        raise ValueError('Relink requires canonical paths without symlinks or dot segments')
    return path


def _name_key(path):
    # Refuse ambiguous case/Unicode spellings even on a case-sensitive host.
    return unicodedata.normalize('NFC', path).casefold()


def _inside(path, roots):
    return any(path.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def _policy(config, user):
    viewer = config.get('viewer', {})
    if not isinstance(viewer, dict) or not isinstance(config.get('users', {}), dict):
        raise ValueError('Invalid viewer/users policy')
    if viewer.get('path_mapping'):
        raise ValueError('Relink does not support viewer.path_mapping; use native canonical paths')
    users = config.get('users', {})
    names = sorted(k for k in users if k != 'shared_directories')
    if names and user not in names:
        raise ValueError('Multi-user relink requires an explicitly configured --user')
    if not names and user is not None:
        raise ValueError('--user is only valid for a configured multi-user install')
    shared = users.get('shared_directories', [])
    if (not isinstance(shared, list) or not isinstance(viewer.get('scan_directories', []), list)
            or any(not isinstance(users[name], dict) or not isinstance(users[name].get('directories', []), list)
                   for name in names)):
        raise ValueError('Configured directories must be lists')
    visibility = {name: users[name].get('directories', []) + shared for name in names}
    roots = list(viewer.get('scan_directories', [])) + shared
    for dirs in visibility.values():
        roots.extend(dirs)
    if not roots or any(not isinstance(root, str) or not root.strip() for root in roots):
        raise ValueError('Relink requires explicit nonblank configured directories')
    resolved = sorted(set(os.path.realpath(root) for root in roots))
    if any(not os.path.isdir(root) or not os.access(root, os.R_OK | os.X_OK) for root in resolved):
        raise ValueError('A configured root is missing or inaccessible')
    return {'user': user, 'roots': resolved,
            'visibility': {name: sorted(set(os.path.realpath(d) for d in dirs))
                           for name, dirs in visibility.items()},
            'raw_decode': config.get('raw_decode', {}),
            'hdr_pq_tonemap': config.get('hdr_pq_tonemap', {})}


def _authorize(old, new, policy):
    if not all(_inside(path, policy['roots']) for path in (old, new)):
        raise ValueError('Both paths must be inside configured roots')
    visible = [tuple(name for name, roots in policy['visibility'].items() if _inside(path, roots))
               for path in (old, new)]
    if policy['visibility'] and (policy['user'] not in visible[0] or visible[0] != visible[1]):
        raise ValueError('Relink would cross a user visibility boundary')


def _stat_stamp(value):
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def _path_stamp(path):
    # On NTFS, stat(path) and fstat(fd) report different ctime for a file whose times were
    # set after creation (every time-preserving copy), so the second stamp must come from
    # the same API as the first. POSIX keeps stat(path).
    if sys.platform != 'win32':
        return _stat_stamp(os.stat(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_BINARY)
    try:
        return _stat_stamp(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def _file_receipt(old, new, policy):
    _canonical(old)
    _canonical(new)
    _authorize(old, new, policy)
    if not is_path_deleted(old):
        raise ValueError('Original must be missing with a readable, existing parent; present/inaccessible originals refused')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(new, flags)
    with os.fdopen(descriptor, 'rb') as handle:
        _canonical(new)
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise ValueError('Destination must be a regular file within the file-size limit')
        digest = hashlib.sha256()
        while block := handle.read(1024 * 1024):
            digest.update(block)
        if _stat_stamp(before) != _stat_stamp(os.fstat(handle.fileno())) or _stat_stamp(before) != _path_stamp(new):
            raise ValueError('Destination changed while hashing')
    return {'old': old, 'new': new, 'sha256': digest.hexdigest(),
            'stat': _stat_stamp(before)}


def _references(conn):
    from db import schema
    declared = {name[:-8].lower(): {column[0] for column in value}
                for name, value in vars(schema).items()
                if name.endswith('_COLUMNS') and isinstance(value, list) and value
                and isinstance(value[0], tuple)}
    declared.update(_AUXILIARY_COLUMNS)
    refs = set()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    internal = {row[1] for row in conn.execute('PRAGMA table_list') if row[0] == 'main' and row[2] == 'shadow'}
    internal.add('sqlite_sequence')
    # FTS5's documented shadow names work on the project's SQLite 3.31 floor;
    # PRAGMA table_list only appeared in 3.37. Never hide arbitrary suffix matches.
    fts = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='photos_fts'").fetchone()
    if fts and re.match(r'\s*CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
                        r'(?:photos_fts|[\"`\[]photos_fts[\"`\]])\s+USING\s+fts5\s*\(',
                        fts[0] or '', re.IGNORECASE):
        internal.update('photos_fts_' + suffix for suffix in ('data', 'idx', 'content', 'docsize', 'config'))
    historical_paths = set(_NON_ASSET_PATHS)
    if 'photo_metadata_edits' in declared:
        # This optional feature's actual schema must declare the table first.
        # Its packet source is history; only the photo_path FK is an asset link.
        historical_paths.add(('photo_metadata_edits', 'source_path'))
    if 'photos_vec' in tables:
        # sqlite-vec 0.1.x does not label its vector chunk table as a shadow, and
        # its labelled shadows are invisible without PRAGMA table_list (< 3.37).
        internal.update('photos_vec_' + suffix for suffix in ('info', 'chunks', 'rowids', 'vector_chunks00'))
    for table in tables:
        if table in internal:
            continue
        quoted = _quote(table)
        for fk in conn.execute(f'PRAGMA foreign_key_list({quoted})'):
            if fk[2] == 'photos':
                if fk[4] != 'path' or fk[1] != 0:
                    raise ValueError('Unsupported composite photo foreign key')
                refs.add((table, fk[3]))
        columns = list(conn.execute(f'PRAGMA table_info({quoted})'))
        own_refs = {column for ref_table, column in refs if ref_table == table}
        if table in declared:
            if {column[1] for column in columns} - declared[table] - own_refs:
                raise ValueError(f'Unregistered schema column in {table}; review dependencies first')
        elif table not in ('photos_fts', 'photos_vec') and not own_refs:
            raise ValueError(f'Unregistered table {table}; review dependencies first')
        for column in columns:
            pair = table, column[1]
            if pair in _PLAIN_REFS or pair == ('photos_vec', 'path'):
                refs.add(pair)
            elif (column[1] == 'path' or column[1].endswith('_path')) and pair not in refs | historical_paths:
                raise ValueError(f'Unregistered path dependency: {table}.{column[1]}')
    return sorted(refs)


def _reference_receipt(conn, refs, old, new):
    receipt = []
    for table, column in refs:
        base = f'SELECT * FROM {_quote(table)} WHERE {_quote(column)}=?'
        if conn.execute(base, (new,)).fetchone() is not None:
            raise ValueError(f'Destination already has dependent rows in {table}')
        rows = sorted(_row_digest(row) for row in conn.execute(base, (old,)))
        receipt.append({'table': table, 'column': column, 'count': len(rows), 'digest': _digest(rows)})
    return receipt


def _sidecar_paths(photo):
    return {'sidecar_full': photo + '.xmp',
            'sidecar_basename': os.path.splitext(photo)[0] + '.xmp',
            'sidecar_facet': photo + '.facet.xmp'}


def _sidecar_owners(candidate, photos):
    key = _name_key(candidate)
    return {photo for photo in photos if key in {_name_key(path) for path in _sidecar_paths(photo).values()}}


def _companions(entry, photos, mapping):
    """Validate explicit relationships; never infer ownership from filenames."""
    from utils.image_loading import RAW_EXTENSIONS
    seen = set()
    for companion in entry.get('companions', []):
        old, new, kind = companion['old'], companion['new'], companion['kind']
        if kind in _sidecar_paths(entry['old']):
            if old != _sidecar_paths(entry['old'])[kind] or new != _sidecar_paths(entry['new'])[kind]:
                raise ValueError('Explicit sidecar mapping does not preserve its naming relationship')
            if len(_sidecar_owners(old, photos)) > 1 or len(_sidecar_owners(new, photos)) > 1:
                raise ValueError('Ambiguous sidecar ownership, including double-extension or case collisions')
        elif kind == 'raw':
            if (Path(old).suffix.lower() not in RAW_EXTENSIONS or Path(old).suffix.lower() != Path(new).suffix.lower()
                    or Path(old).with_suffix('') != Path(entry['old']).with_suffix('')
                    or Path(new).with_suffix('') != Path(entry['new']).with_suffix('')):
                raise ValueError('Explicit RAW mapping does not preserve the culling companion relationship')
        else:
            raise ValueError('Unknown explicit companion kind')
        if new in seen:
            raise ValueError('A companion was supplied twice')
        seen.add(new)
    # Avoid adopting destination sidecars which were never in the reviewed map.
    siblings = list(Path(entry['new']).parent.iterdir())
    sidecar_keys = {_name_key(path) for path in _sidecar_paths(entry['new']).values()}
    for candidate in siblings:
        if _name_key(str(candidate)) in sidecar_keys and str(candidate) not in seen:
            raise ValueError('Destination sidecar requires an explicit companion mapping')
    if Path(entry['new']).suffix.lower() not in RAW_EXTENSIONS:
        candidates = [str(path) for path in siblings
                      if path.suffix.lower() in RAW_EXTENSIONS
                      and _name_key(path.stem) == _name_key(Path(entry['new']).stem)]
        if len(candidates) > 1:
            raise ValueError('Multiple possible RAW companions; relationship is ambiguous')
        # Indexed RAWs are independently relinked photos, not duplicate file
        # companions. An explicit top-level mapping must preserve both stems.
        indexed_raws = {item['new'] for item in mapping if item['old'] in photos
                        and Path(item['old']).suffix.lower() in RAW_EXTENSIONS
                        and _name_key(str(Path(item['old']).with_suffix('')))
                        == _name_key(str(Path(entry['old']).with_suffix('')))
                        and _name_key(str(Path(item['new']).with_suffix('')))
                        == _name_key(str(Path(entry['new']).with_suffix('')))}
        if any(path not in seen | indexed_raws for path in candidates):
            raise ValueError('Destination RAW requires an explicit companion mapping or indexed RAW relink entry')


def _validate_mapping(mapping):
    if not isinstance(mapping, list) or not 1 <= len(mapping) <= MAX_PHOTOS:
        raise ValueError(f'Mapping must contain 1–{MAX_PHOTOS} photo entries')
    for entry in mapping:
        if (not isinstance(entry, dict) or not {'old', 'new'} <= entry.keys()
                or entry.keys() - {'old', 'new', 'companions'}
                or not isinstance(entry.get('companions', []), list)):
            raise ValueError('Mapping entries require only old/new and optional explicit companions')
        for item in [entry, *entry.get('companions', [])]:
            if (not isinstance(item, dict) or not isinstance(item.get('old'), str)
                    or not isinstance(item.get('new'), str)):
                raise ValueError('Every mapping requires string old/new paths')
            if item is not entry and item.keys() != {'old', 'new', 'kind'}:
                raise ValueError('Companions require exactly old/new/kind')
    if sum(1 + len(entry.get('companions', [])) for entry in mapping) > MAX_FILES:
        raise ValueError('Too many explicitly mapped files')


@contextmanager
def _connection(db_path, write=False):
    path = Path(db_path).resolve(strict=True)
    conn = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        load_sqlite_vec(conn)
        yield conn
    finally:
        conn.close()


def _entry_file_receipts(entry, policy, photos, names, seen):
    """Receipts for one mapping entry and its companions; ``seen`` carries the plan-wide duplicate and size tallies."""
    receipts = []
    for item in [entry, *entry.get('companions', [])]:
        if _name_key(item['old']) in seen['sources'] or _name_key(item['new']) in seen['targets']:
            raise ValueError('A source file was supplied more than once')
        seen['sources'].add(_name_key(item['old']))
        seen['targets'].add(_name_key(item['new']))
        if item is not entry and _name_key(item['new']) in names:
            raise ValueError('Companion destination is already a registered photo')
        receipt = _file_receipt(item['old'], item['new'], policy)
        inode = tuple(receipt['stat'][:2])
        if inode in seen['inodes'] or (item is entry and receipt['sha256'] in seen['hashes']):
            raise ValueError('Duplicate/copied destinations in the plan')
        seen['inodes'].add(inode)
        if item is entry:
            seen['hashes'].add(receipt['sha256'])
        seen['bytes'] += receipt['stat'][2]
        seen['files'] += 1
        if seen['bytes'] > MAX_TOTAL_BYTES or seen['files'] > MAX_FILES:
            raise ValueError('Relink plan exceeds total file/byte limits')
        if item is not entry and item['old'] in photos:
            raise ValueError('Indexed companions need their own top-level relink entry')
        receipts.append(receipt)
    return receipts


def _build_plan(conn, db_path, mapping, config, user):
    from utils.image_loading import (SCANNABLE_IMAGE_EXTENSIONS, configure_raw_decode_profile,
                                     configure_hdr_pq_tonemap_profile)
    from utils.manual_face_frame import source_identity
    _validate_mapping(mapping)
    policy = _policy(config, user)
    configure_raw_decode_profile(policy['raw_decode'])
    configure_hdr_pq_tonemap_profile(policy['hdr_pq_tonemap'])
    refs = _references(conn)
    if conn.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('Database already has broken foreign keys; repair before relinking')
    photos = [r[0] for r in conn.execute('SELECT path FROM photos')]
    names = {_name_key(path) for path in photos}
    planned_names, sources = set(), set()
    seen = {'inodes': set(), 'hashes': set(), 'sources': set(), 'targets': set(), 'bytes': 0, 'files': 0}
    source_name_counts = {}
    for path in photos:
        key = _name_key(path)
        source_name_counts[key] = source_name_counts.get(key, 0) + 1
    receipts = []
    # Both old and proposed photo names take part in sidecar ambiguity checks.
    photo_names = photos + [entry['new'] for entry in mapping]
    for entry in mapping:
        old, new = entry['old'], entry['new']
        if (old in sources or _name_key(new) in names | planned_names or _name_key(old) == _name_key(new)
                or source_name_counts.get(_name_key(old), 0) > 1):
            raise ValueError('Repeated source, existing destination, or case/Unicode-only mapping')
        sources.add(old)
        planned_names.add(_name_key(new))
        row = conn.execute('SELECT rowid,* FROM photos WHERE path=?', (old,)).fetchone()
        if row is None:
            raise ValueError('Source is not a registered photo')
        if Path(new).suffix.lower() not in SCANNABLE_IMAGE_EXTENSIONS or Path(old).suffix.lower() != Path(new).suffix.lower():
            raise ValueError('Relink cannot change the image format/extension')
        _canonical(old)
        _canonical(new)
        _authorize(old, new, policy)
        _companions(entry, photo_names, mapping)
        file_receipts = _entry_file_receipts(entry, policy, photos, names, seen)
        # This proves the target decodes in canonical analysis space, not that
        # its bytes equal the missing original. All manual marks need review.
        frame = json.loads(source_identity(new))
        dimensions = conn.execute('SELECT image_width,image_height FROM photos WHERE path=?', (old,)).fetchone()
        if all(dimensions) and list(dimensions) != [frame['w'], frame['h']]:
            raise ValueError('Destination canonical dimensions differ from the stored photo')
        if file_receipts[0]['stat'] != _path_stamp(new):
            raise ValueError('Destination changed while decoding')
        receipts.append({'old': old, 'new': new, 'source_digest': _row_digest(row),
                         'identity': 'original_bytes_unknown', 'target_dimensions': [frame['w'], frame['h']],
                         'files': file_receipts, 'references': _reference_receipt(conn, refs, old, new)})
    db_stat = os.stat(db_path)
    schema = list(conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name"))
    body = {'version': 1, 'database': str(Path(db_path).resolve()),
            'database_inode': [db_stat.st_dev, db_stat.st_ino], 'schema': _digest(schema),
            'policy': policy, 'mapping': mapping, 'entries': receipts,
            'source_mount_status': 'not_verified; operator must confirm sources are moved, not offline',
            'remote_sync_state': 'unchanged; no verified remote identity binding',
            'companions': 'explicit mappings only; unknown missing companions cannot be discovered'}
    plan = {**body, 'plan_id': _digest(body)}
    if len(json.dumps(plan, ensure_ascii=False, indent=2).encode()) > MAX_PLAN_BYTES:
        raise ValueError('Generated plan exceeds the 2 MiB input limit; use a smaller batch')
    return plan


def preview_relinks(db_path, mapping, config, user=None):
    """Read-only DB preview; hashes/decodes only explicitly named target files."""
    with _connection(db_path) as conn:
        return _build_plan(conn, db_path, mapping, config, user)


def _rewrite_refs(conn, refs, old, new):
    for table, column in refs:
        if table == 'photos_vec':
            vector = conn.execute('SELECT embedding FROM photos_vec WHERE path=?', (old,)).fetchone()
            if vector:
                conn.execute('DELETE FROM photos_vec WHERE path=?', (old,))
                conn.execute('INSERT INTO photos_vec(path,embedding) VALUES (?,?)', (new, vector[0]))
        else:
            conn.execute(f'UPDATE {_quote(table)} SET {_quote(column)}=? WHERE {_quote(column)}=?', (new, old))


def _flag_manual_faces(conn, path):
    """Every manual rectangle on a relinked photo needs review; v2 sources also carry the unverified marker."""
    for face_id, source in conn.execute('SELECT id,manual_source FROM faces WHERE photo_path=? AND is_manual=1', (path,)).fetchall():
        try:
            stored = json.loads(source)
            if isinstance(stored, dict) and stored.get('v') == 2:
                source = _json({**stored, 'relink_unverified': True})
        except (ValueError, TypeError):
            pass
        conn.execute('UPDATE faces SET manual_source=?,manual_review_required=1 WHERE id=?', (source, face_id))


def apply_relinks(db_path, plan, config, *, acknowledge_plan, acknowledge_unverified_identity=False, user=None):
    """Apply exactly a reviewed plan atomically; never move files or contact servers."""
    if not isinstance(plan, dict):
        raise ValueError('Apply requires a reviewed preview object')
    body = {k: v for k, v in plan.items() if k != 'plan_id'}
    if acknowledge_plan != plan.get('plan_id') or _digest(body) != acknowledge_plan:
        raise ValueError('Exact reviewed plan acknowledgment required')
    if not acknowledge_unverified_identity:
        raise ValueError('Explicit acknowledgment of unknown original bytes is required')
    with _connection(db_path, write=True) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            current = _build_plan(conn, db_path, plan['mapping'], config, user)
            if current != plan:
                raise ValueError('Relink plan is stale; preview and review again')
            conn.execute('PRAGMA defer_foreign_keys=ON')
            refs = _references(conn)
            for entry in plan['entries']:
                old, new = entry['old'], entry['new']
                conn.execute('UPDATE photos SET path=?,filename=? WHERE path=?', (new, Path(new).name, old))
                _rewrite_refs(conn, refs, old, new)
                _flag_manual_faces(conn, new)
            evict_derived_stats_cache(conn)
            invalidate_metric_ranges(conn)
            if conn.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Relink would break a foreign key')
            for entry in plan['entries']:
                for item in entry['files']:
                    if _file_receipt(item['old'], item['new'], plan['policy']) != item:
                        raise ValueError('A file changed before commit')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return {'relinked': len(plan['entries']), 'plan_id': plan['plan_id'],
            'identity': 'operator_asserted; original_bytes_unknown', 'remote_sync_state': 'unchanged'}


def main(argv=None, *, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--user')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--mapping', help='JSON list of explicit old/new/companions entries; preview only')
    mode.add_argument('--apply-plan', help='Previously saved and reviewed preview JSON')
    parser.add_argument('--plan-out', help='Create a new preview file; never overwrite an existing file')
    parser.add_argument('--ack-plan')
    parser.add_argument('--acknowledge-unverified-identity', action='store_true')
    args = parser.parse_args(argv)
    from config_resolve import load_resolved
    def read_json(path):
        with open(path, 'rb') as handle:
            data = handle.read(MAX_PLAN_BYTES + 1)
        if len(data) > MAX_PLAN_BYTES:
            raise ValueError('Mapping/plan exceeds the 2 MiB input limit')
        return json.loads(data)
    try:
        config = load_resolved(args.config)
        if args.mapping:
            if args.ack_plan or args.acknowledge_unverified_identity:
                raise ValueError('Apply acknowledgments are invalid in preview mode')
            result = preview_relinks(args.db, read_json(args.mapping), config, args.user)
            if args.plan_out:
                descriptor = os.open(args.plan_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                    json.dump(result, handle, ensure_ascii=False, indent=2)
        else:
            if args.plan_out:
                raise ValueError('--plan-out is only valid for preview')
            from facet import LIBRARY_JOB_MAINTENANCE, hold_library_lock_or_exit
            plan = read_json(args.apply_plan)
            lock = hold_library_lock_or_exit(args.db, LIBRARY_JOB_MAINTENANCE)
            try:
                result = apply_relinks(args.db, plan, config, acknowledge_plan=args.ack_plan,
                                       acknowledge_unverified_identity=args.acknowledge_unverified_identity, user=args.user)
            finally:
                lock.release()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(1, f'Relink refused: {exc}\n')


if __name__ == '__main__':
    main()
