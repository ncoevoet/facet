"""Logical-photo review authority, independent from display-primary paths.

Callers supply only currently authorized file labels for inheritance. Mutations
use the caller's transaction; original photo/preference rows remain untouched.
Viewer synchronization owns import receipts; collection/API integration must
use these explicit account and snapshot boundaries.
"""
from contextlib import contextmanager
from db.transactions import savepoint
import hashlib
import hmac
import json
import os
import re
import sqlite3

from db.logical_assets import AssetConflict, _members

FIELDS = frozenset(('star_rating', 'is_favorite', 'is_kept', 'is_rejected'))
DECISION = frozenset(('is_kept', 'is_rejected'))


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_review_seeds (
        asset_id TEXT PRIMARY KEY,
        photo_path TEXT)''')
    # Photo delete/relink triggers must not scan active and retired seeds.
    conn.execute('CREATE INDEX IF NOT EXISTS logical_review_seeds_path ON logical_review_seeds(photo_path)')
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_review_fields (
        asset_id TEXT NOT NULL,
        owner TEXT NOT NULL, field TEXT NOT NULL,
        value INTEGER, origin TEXT NOT NULL CHECK(origin IN ('user','agent')),
        PRIMARY KEY(asset_id,owner,field),
        CHECK(field IN ('star_rating','is_favorite','decision')),
        CHECK((field='star_rating' AND (value IS NULL OR (typeof(value)='integer' AND value BETWEEN 0 AND 5)))
           OR (field='is_favorite' AND typeof(value)='integer' AND value IN (0,1))
           OR (field='decision' AND typeof(value)='integer' AND value IN (0,1,2))))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_review_versions (
        asset_id TEXT NOT NULL,
        owner TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
        PRIMARY KEY(asset_id,owner))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_review_field_versions (
        asset_id TEXT NOT NULL, owner TEXT NOT NULL, field TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>0),
        CHECK(field IN ('star_rating','is_favorite','decision')), PRIMARY KEY(asset_id,owner,field))''')
    for event, reference in [('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')]:
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS logical_review_clock_{event.lower()}
            AFTER {event} ON logical_review_fields
            WHEN EXISTS(SELECT 1 FROM logical_assets WHERE id={reference}.asset_id) BEGIN
            INSERT INTO logical_review_versions(asset_id,owner,revision)
                VALUES ({reference}.asset_id,{reference}.owner,1)
            ON CONFLICT(asset_id,owner) DO UPDATE SET revision=revision+1;
            INSERT INTO logical_review_field_versions(asset_id,owner,field,revision)
                VALUES ({reference}.asset_id,{reference}.owner,{reference}.field,1)
            ON CONFLICT(asset_id,owner,field) DO UPDATE SET revision=revision+1;
            END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_review_immutable_key
        BEFORE UPDATE OF asset_id,owner,field ON logical_review_fields
        WHEN OLD.asset_id IS NOT NEW.asset_id OR OLD.owner IS NOT NEW.owner OR OLD.field IS NOT NEW.field
        BEGIN SELECT RAISE(ABORT,'Logical review keys are immutable'); END""")
    # Review rows and clocks survive retirement of a logical identity. Active
    # reads still require authorized members; full viewer exports omit archives.
    conn.execute('''CREATE TRIGGER IF NOT EXISTS logical_review_photo_delete
        BEFORE DELETE ON photos BEGIN
        UPDATE logical_review_seeds SET photo_path=NULL WHERE photo_path=OLD.path;
        END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS logical_review_photo_move
        AFTER UPDATE OF path ON photos WHEN OLD.path IS NOT NEW.path BEGIN
        UPDATE logical_review_seeds SET photo_path=NEW.path WHERE photo_path=OLD.path
          AND EXISTS(SELECT 1 FROM logical_asset_members m WHERE m.asset_id=logical_review_seeds.asset_id
                     AND m.photo_path IN (OLD.path,NEW.path));
        END''')


@contextmanager
def _transaction(conn):
    if not conn.in_transaction:
        raise AssetConflict('A catalog transaction is required')
    with savepoint(conn):
        yield


def seed(conn, asset_id, source_path, revision, *, visibility_sql, visibility_params=()):
    """Capture an explicit inheritance source once; primary changes never replace it."""
    with _transaction(conn):
        paths = _members(conn, asset_id, revision, visibility_sql, visibility_params)
        if source_path not in paths:
            raise AssetConflict('Choose an authorized current review source')
        existing = conn.execute('SELECT photo_path FROM logical_review_seeds WHERE asset_id=?', (asset_id,)).fetchone()
        if existing and existing[0] != source_path:
            raise AssetConflict('The logical review source is already chosen')
        conn.execute('INSERT INTO logical_review_seeds VALUES (?,?) ON CONFLICT(asset_id) DO NOTHING',
                     (asset_id, source_path))


def database_identity(filename, memory_identity=None):
    if filename:
        info = os.stat(filename)
        return [os.path.realpath(filename), info.st_dev, info.st_ino]
    return ['memory', memory_identity]


def resolve(asset_id, owner, file_labels, members, source_path, overrides, revision, database, group):
    """Pure resolution shared by sync and async readers of one authorized snapshot."""
    allowed = members & file_labels.keys()
    if not allowed:
        raise AssetConflict('Logical review unavailable')
    source = source_path if source_path in allowed else None
    inherited = file_labels[source] if source is not None else {}
    values = {field: inherited.get(field) for field in FIELDS}
    origins = {field: 'file' if field in inherited else 'unknown' for field in FIELDS}
    # Existing file rows may hold contradictory historical flags. Rejection
    # wins, matching the gallery; the original row remains unchanged.
    if values['is_rejected']:
        values['is_kept'], values['is_rejected'] = 0, 1
    elif values['is_kept']:
        values['is_kept'], values['is_rejected'] = 1, 0
    for field, value, origin in overrides:
        if field == 'decision':
            values['is_kept'], values['is_rejected'] = int(value == 1), int(value == 2)
            origins['is_kept'] = origins['is_rejected'] = origin
        else:
            values[field] = value
            origins[field] = origin
    visible_group = [group[0] if group[0] in allowed else None, group[1]] if group else None
    inputs = [database, asset_id, owner, visible_group, sorted(allowed), source,
              {path: file_labels[path] for path in sorted(allowed)}, overrides]
    token = hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
    return {'values': values, 'origins': origins, 'source_path': source,
            'input_token': token, 'revision': revision}



def read(conn, asset_id, owner, file_labels):
    """Resolve sparse overrides from currently authorized labels in one transaction."""
    if not conn.in_transaction:
        raise AssetConflict('A catalog read transaction is required')
    if not isinstance(owner, str):
        raise AssetConflict('Choose an account review scope')
    members = {row[0] for row in conn.execute('SELECT photo_path FROM logical_asset_members WHERE asset_id=?', (asset_id,))}
    seed_row = conn.execute('SELECT photo_path FROM logical_review_seeds WHERE asset_id=?', (asset_id,)).fetchone()
    overrides = [tuple(row) for row in conn.execute(
        'SELECT field,value,origin FROM logical_review_fields WHERE asset_id=? AND owner=? ORDER BY field', (asset_id, owner))]
    version = conn.execute('SELECT revision FROM logical_review_versions WHERE asset_id=? AND owner=?', (asset_id, owner)).fetchone()
    filename = next(row[2] for row in conn.execute('PRAGMA database_list') if row[1] == 'main')
    group = conn.execute('SELECT primary_path,revision FROM logical_assets WHERE id=?', (asset_id,)).fetchone()
    return resolve(asset_id, owner, file_labels, members, seed_row[0] if seed_row else None,
                   overrides, version[0] if version else 0, database_identity(filename, id(conn)), group)


def _check_inputs(state, token):
    if (not isinstance(token, str) or re.fullmatch(r'[0-9a-f]{64}', token) is None
            or not hmac.compare_digest(token, state['input_token'])):
        raise AssetConflict('Logical review inputs changed; review again')


def _check_version(conn, asset_id, owner, expected):
    row = conn.execute('SELECT revision FROM logical_review_versions WHERE asset_id=? AND owner=?', (asset_id, owner)).fetchone()
    current = row[0] if row else 0
    if type(expected) is not int or expected < 0 or current != expected:
        raise AssetConflict('Logical review changed; review again')
    return current


def _check_current(conn, asset_id, owner):
    row = conn.execute('SELECT revision FROM logical_review_versions WHERE asset_id=? AND owner=?', (asset_id, owner)).fetchone()
    return row[0] if row else 0


def _advance(conn, asset_id, owner, revision):
    conn.execute('INSERT INTO logical_review_versions VALUES (?,?,?) ON CONFLICT(asset_id,owner) '
                 'DO UPDATE SET revision=excluded.revision', (asset_id, owner, revision + 1))
    return revision + 1


def set_fields(conn, asset_id, owner, group_revision, review_revision, patch, *, origin,
               visibility_sql, file_labels, input_token, visibility_params=()):
    if (not isinstance(owner, str) or origin not in ('user', 'agent') or not isinstance(patch, dict)
            or not patch or not patch.keys() <= FIELDS):
        raise AssetConflict('Choose supported logical review fields')
    if patch.keys() & DECISION and not DECISION <= patch.keys():
        raise AssetConflict('Keep and Reject must be supplied as one decision')
    if patch.get('is_kept') and patch.get('is_rejected'):
        raise AssetConflict('A photo cannot be both kept and rejected')
    for field, value in patch.items():
        if field == 'star_rating':
            valid = value is None or type(value) is int and 0 <= value <= 5
        else:
            valid = type(value) is int and value in (0, 1)
        if not valid:
            raise AssetConflict('Invalid logical review value')
    with _transaction(conn):
        paths = _members(conn, asset_id, group_revision, visibility_sql, visibility_params)
        if not set(paths) <= file_labels.keys():
            raise AssetConflict('Logical review inputs are incomplete')
        current = _check_version(conn, asset_id, owner, review_revision)
        state = read(conn, asset_id, owner, file_labels)
        _check_inputs(state, input_token)
        if origin == 'agent':
            before = state['values']
            changed = {field for field, value in patch.items() if value != before[field]}
            if changed & DECISION:
                changed.update(DECISION)
            patch = {field: value for field, value in patch.items() if field in changed}
            if not patch:
                return current
        stored = {field: value for field, value in patch.items() if field not in DECISION}
        if patch.keys() & DECISION:
            stored['decision'] = 2 if patch['is_rejected'] else 1 if patch['is_kept'] else 0
        conn.executemany('INSERT INTO logical_review_fields VALUES (?,?,?,?,?) '
                         'ON CONFLICT(asset_id,owner,field) DO UPDATE SET value=excluded.value,origin=excluded.origin',
                         [(asset_id, owner, field, value, origin) for field, value in stored.items()])
        return _check_current(conn, asset_id, owner)


def reset_fields(conn, asset_id, owner, group_revision, review_revision, fields, *,
                 visibility_sql, file_labels, input_token, visibility_params=()):
    if not isinstance(fields, (list, tuple, set, frozenset)) or not isinstance(owner, str):
        raise AssetConflict('Choose logical review fields to reset')
    fields = set(fields)
    if not fields or not fields <= FIELDS or fields & DECISION and not DECISION <= fields:
        raise AssetConflict('Choose complete logical review fields to reset')
    with _transaction(conn):
        paths = _members(conn, asset_id, group_revision, visibility_sql, visibility_params)
        if not set(paths) <= file_labels.keys():
            raise AssetConflict('Logical review inputs are incomplete')
        _check_version(conn, asset_id, owner, review_revision)
        state = read(conn, asset_id, owner, file_labels)
        _check_inputs(state, input_token)
        stored = {('decision' if field in DECISION else field) for field in fields}
        for field in stored:
            deleted = conn.execute('DELETE FROM logical_review_fields WHERE asset_id=? AND owner=? AND field=?',
                                   (asset_id, owner, field)).rowcount
            if not deleted:
                conn.execute('INSERT INTO logical_review_field_versions VALUES (?,?,?,1) '
                             'ON CONFLICT(asset_id,owner,field) DO UPDATE SET revision=revision+1',
                             (asset_id, owner, field))
                _advance(conn, asset_id, owner, _check_current(conn, asset_id, owner))
        return _check_current(conn, asset_id, owner)
