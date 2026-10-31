"""Owner-private manual stacks. Mutations use the caller's transaction.

No photo foreign key: scanner INSERT OR REPLACE must preserve organization.
Explicit photo-delete/path-update triggers maintain membership for every writer.
"""
import sqlite3
import uuid
from typing import Any

from db import organization_history as history

MAX_MEMBERS = 1000
# SQLite before 3.32 caps a statement at 999 bound variables; the supported floor
# is that older limit, so every IN list shares it with the caller's own binds.
SQLITE_MAX_BINDS = 999
IN_CHUNK = 300


class StackError(ValueError):
    """Safe, public refusal with an HTTP-compatible status."""

    def __init__(self, message: str = 'Stack unavailable', status: int = 409):
        super().__init__(message)
        self.status = status


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS photo_stacks (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, cover_path TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>0), UNIQUE(id,owner))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS photo_stack_members (
        stack_id TEXT NOT NULL, owner TEXT NOT NULL, photo_path TEXT NOT NULL,
        position INTEGER NOT NULL CHECK(position>=0),
        PRIMARY KEY(stack_id,photo_path), UNIQUE(owner,photo_path),
        UNIQUE(stack_id,position),
        FOREIGN KEY(stack_id,owner) REFERENCES photo_stacks(id,owner) ON DELETE CASCADE)""")
    # One row per member of a skipped suggestion; `key` is the suggestion's content hash.
    conn.execute("""CREATE TABLE IF NOT EXISTS stack_suggestion_dismissals (
        owner TEXT NOT NULL, key TEXT NOT NULL, kind TEXT NOT NULL, size INTEGER NOT NULL,
        photo_path TEXT NOT NULL, PRIMARY KEY(owner,key,photo_path))""")
    conn.execute('CREATE INDEX IF NOT EXISTS stack_suggestion_dismissals_path '
                 'ON stack_suggestion_dismissals(photo_path)')
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_stack_suggestion_photos_delete
        AFTER DELETE ON photos BEGIN
        DELETE FROM stack_suggestion_dismissals WHERE photo_path=OLD.path;
        END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_stack_suggestion_photos_move
        AFTER UPDATE OF path ON photos WHEN OLD.path IS NOT NEW.path BEGIN
        UPDATE stack_suggestion_dismissals SET photo_path=NEW.path WHERE photo_path=OLD.path;
        END""")
    conn.execute('CREATE INDEX IF NOT EXISTS photo_stacks_owner ON photo_stacks(owner,id)')
    conn.execute('CREATE INDEX IF NOT EXISTS photo_stack_members_path ON photo_stack_members(photo_path)')
    # Explicit cleanup also works for external writers with foreign_keys=OFF.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_stack_delete
        AFTER DELETE ON photo_stacks BEGIN
        DELETE FROM photo_stack_members WHERE stack_id=OLD.id;
        END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_stack_photos_delete
        BEFORE DELETE ON photos WHEN EXISTS(SELECT 1 FROM photo_stack_members WHERE photo_path=OLD.path) BEGIN
        UPDATE organization_clock SET revision=revision+1 WHERE id=1;
        INSERT INTO organization_revisions(path,kind,scope,revision)
        SELECT m.photo_path,'stack',m.owner,(SELECT revision FROM organization_clock WHERE id=1)
        FROM photo_stack_members m WHERE m.stack_id IN
            (SELECT stack_id FROM photo_stack_members WHERE photo_path=OLD.path)
        ON CONFLICT(path,kind,scope) DO UPDATE SET revision=excluded.revision;
        UPDATE photo_stacks SET revision=(SELECT revision FROM organization_clock WHERE id=1),
            cover_path=COALESCE((SELECT photo_path FROM photo_stack_members
                WHERE stack_id=photo_stacks.id AND photo_path!=OLD.path ORDER BY position LIMIT 1),cover_path)
        WHERE id IN (SELECT stack_id FROM photo_stack_members WHERE photo_path=OLD.path)
            AND cover_path=OLD.path;
        UPDATE photo_stacks SET revision=(SELECT revision FROM organization_clock WHERE id=1)
        WHERE id IN (SELECT stack_id FROM photo_stack_members WHERE photo_path=OLD.path);
        DELETE FROM photo_stacks WHERE id IN
            (SELECT stack_id FROM photo_stack_members WHERE photo_path=OLD.path)
            AND (SELECT COUNT(*) FROM photo_stack_members WHERE stack_id=photo_stacks.id)<=2;
        DELETE FROM photo_stack_members WHERE photo_path=OLD.path;
        END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_stack_photos_move
        AFTER UPDATE OF path ON photos WHEN OLD.path IS NOT NEW.path
            AND EXISTS(SELECT 1 FROM photo_stack_members WHERE photo_path=OLD.path) BEGIN
        UPDATE organization_clock SET revision=revision+1 WHERE id=1;
        UPDATE photo_stack_members SET photo_path=NEW.path WHERE photo_path=OLD.path;
        UPDATE photo_stacks SET cover_path=NEW.path WHERE cover_path=OLD.path;
        UPDATE photo_stacks SET revision=(SELECT revision FROM organization_clock WHERE id=1)
        WHERE id IN (SELECT stack_id FROM photo_stack_members WHERE photo_path=NEW.path);
        INSERT INTO organization_revisions(path,kind,scope,revision)
        SELECT m.photo_path,'stack',m.owner,(SELECT revision FROM organization_clock WHERE id=1)
        FROM photo_stack_members m WHERE m.stack_id IN
            (SELECT stack_id FROM photo_stack_members WHERE photo_path=NEW.path)
        ON CONFLICT(path,kind,scope) DO UPDATE SET revision=excluded.revision;
        END""")


def visibility_chunk_size(extra_binds: int) -> int:
    """Largest IN-list chunk that fits beside ``extra_binds`` other bound variables.

    The supported SQLite floor allows ``SQLITE_MAX_BINDS`` (999) variables per
    statement, shared with directory-visibility binds; chunks never exceed
    ``IN_CHUNK`` and always hold at least one key.
    """
    return max(1, min(IN_CHUNK, SQLITE_MAX_BINDS - extra_binds))


def check_paths(paths: list[str], minimum: int) -> None:
    """Refuse a non-distinct, malformed or out-of-range explicit photo list."""
    if (not minimum <= len(paths) <= MAX_MEMBERS
            or any(not isinstance(p, str) or not p or '\x00' in p for p in paths)
            or len(set(paths)) != len(paths)):
        bounds = f'{minimum}\u2013{MAX_MEMBERS}' if minimum else f'at most {MAX_MEMBERS}'
        raise StackError(f'Choose distinct explicit photos ({bounds})', 422)


def transaction(conn: sqlite3.Connection) -> None:
    if not conn.in_transaction:
        raise RuntimeError('Stack mutations require a caller-owned transaction')


def visible_paths(conn: sqlite3.Connection, paths: list[str], visibility_sql: str,
                  visibility_params: tuple | list) -> set[str]:
    from api.db_helpers import select_in_chunks
    return {r[0] for r in select_in_chunks(
        conn, f'SELECT photos.path FROM photos WHERE photos.path IN ({{placeholders}}) AND ({visibility_sql})',
        paths, after=visibility_params, chunk=visibility_chunk_size(len(visibility_params)))}


def get_stack(conn: sqlite3.Connection, owner: str, stack_id: str, *,
              visibility_sql: str = '1=1', visibility_params: tuple | list = (),
              editable: bool = True) -> dict[str, Any] | None:
    row = conn.execute('SELECT id,revision,cover_path FROM photo_stacks WHERE id=? AND owner=?', (stack_id, owner)).fetchone()
    if row is None:
        return None
    members = [dict(path=r[0], position=r[1]) for r in conn.execute(
        'SELECT photo_path,position FROM photo_stack_members WHERE stack_id=? AND owner=? ORDER BY position', (stack_id, owner))]
    permitted = visible_paths(conn, [m['path'] for m in members], visibility_sql, visibility_params)
    visible = [dict(path=m['path'], position=i) for i, m in enumerate(m for m in members if m['path'] in permitted)]
    if not visible:
        return None
    from db.preview_versions import attach_preview_versions
    attach_preview_versions(conn, visible)
    return dict(id=row[0], revision=row[1], cover_path=row[2] if row[2] in permitted else visible[0]['path'],
                members=visible, editable=editable and len(visible) == len(members))


def get_stack_by_photo(conn: sqlite3.Connection, owner: str, path: str, **kwargs) -> dict[str, Any] | None:
    if path not in visible_paths(conn, [path], kwargs.get('visibility_sql', '1=1'), kwargs.get('visibility_params', ())):
        return None
    row = conn.execute('SELECT stack_id FROM photo_stack_members WHERE owner=? AND photo_path=?', (owner, path)).fetchone()
    return get_stack(conn, owner, row[0], **kwargs) if row else None


def _validate(conn, owner, paths, cover_path, stack_id, visibility_sql, visibility_params):
    check_paths(paths, 0)
    if cover_path is not None and cover_path not in paths:
        raise StackError('Cover must be a member', 422)
    if len(visible_paths(conn, paths, visibility_sql, visibility_params)) != len(paths):
        raise StackError()
    from api.db_helpers import select_in_chunks
    if next(select_in_chunks(
            conn, 'SELECT 1 FROM photo_stack_members WHERE owner=? AND photo_path IN ({placeholders}) '
            'AND stack_id!=? LIMIT 1', paths, before=[owner], after=[stack_id], chunk=IN_CHUNK), None):
        raise StackError('A selected photo already belongs to a stack; remove it there first')


def stamp(conn, owner, paths):
    conn.execute('UPDATE organization_clock SET revision=revision+1 WHERE id=1')
    revision = conn.execute('SELECT revision FROM organization_clock WHERE id=1').fetchone()[0]
    conn.executemany("""INSERT INTO organization_revisions(path,kind,scope,revision) VALUES (?,'stack',?,?)
        ON CONFLICT(path,kind,scope) DO UPDATE SET revision=excluded.revision""", [(p, owner, revision) for p in paths])
    return revision


def write(conn, owner, stack_id, paths, cover_path, revision):
    conn.execute('DELETE FROM photo_stack_members WHERE stack_id=? AND owner=?', (stack_id, owner))
    if len(paths) < 2:
        conn.execute('DELETE FROM photo_stacks WHERE id=? AND owner=?', (stack_id, owner))
        return
    conn.execute("""INSERT INTO photo_stacks(id,owner,cover_path,revision) VALUES (?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET cover_path=excluded.cover_path,revision=excluded.revision""",
        (stack_id, owner, cover_path, revision))
    conn.executemany('INSERT INTO photo_stack_members(stack_id,owner,photo_path,position) VALUES (?,?,?,?)',
                     [(stack_id, owner, path, i) for i, path in enumerate(paths)])


def finish(conn, owner, before, stack_id):
    history.record(conn, owner, 'stack', owner, before)
    row = conn.execute("SELECT id FROM organization_history WHERE owner=? AND kind='stack' ORDER BY id DESC LIMIT 1", (owner,)).fetchone()
    return dict(stack=get_stack(conn, owner, stack_id), undo=dict(entry_id=row[0]) if row else None)


def create_stack(conn: sqlite3.Connection, owner: str, paths: list[str], cover_path: str, *,
                 visibility_sql: str = '1=1', visibility_params: tuple | list = ()) -> dict[str, Any]:
    transaction(conn)
    if len(paths) < 2 or cover_path is None:
        raise StackError('A stack needs at least two photos and a cover', 422)
    stack_id = str(uuid.uuid4())
    _validate(conn, owner, paths, cover_path, stack_id, visibility_sql, visibility_params)
    before = history.snapshot(conn, 'stack', owner, paths)
    revision = stamp(conn, owner, paths)
    write(conn, owner, stack_id, paths, cover_path, revision)
    return finish(conn, owner, before, stack_id)


def update_stack(conn: sqlite3.Connection, owner: str, stack_id: str, paths: list[str],
                 cover_path: str | None, expected_revision: int, *,
                 visibility_sql: str = '1=1', visibility_params: tuple | list = ()) -> dict[str, Any]:
    transaction(conn)
    stack = get_stack(conn, owner, stack_id, visibility_sql=visibility_sql, visibility_params=visibility_params)
    if not stack or not stack['editable'] or stack['revision'] != expected_revision:
        raise StackError()
    _validate(conn, owner, paths, cover_path, stack_id, visibility_sql, visibility_params)
    chosen_cover = cover_path or (stack['cover_path'] if stack['cover_path'] in paths else paths[0] if paths else None)
    old_paths = [m['path'] for m in stack['members']]
    if old_paths == paths and stack['cover_path'] == chosen_cover:
        return dict(stack=stack, undo=None)
    affected = list(dict.fromkeys([*old_paths, *paths]))
    before = history.snapshot(conn, 'stack', owner, affected)
    revision = stamp(conn, owner, affected)
    write(conn, owner, stack_id, paths, chosen_cover, revision)
    return finish(conn, owner, before, stack_id)


def delete_stack(conn: sqlite3.Connection, owner: str, stack_id: str, expected_revision: int, **kwargs) -> dict[str, Any]:
    return update_stack(conn, owner, stack_id, [], None, expected_revision, **kwargs)


def restore(conn: sqlite3.Connection, owner: str, changes: list[dict[str, Any]]) -> None:
    """Restore a validated whole history entry; the caller checks visibility/revisions."""
    transaction(conn)
    paths = [c['path'] for c in changes]
    current_ids = {c['after'][0] for c in changes if c['after']}
    before_ids = {c['before'][0] for c in changes if c['before']}
    for stack_id in current_ids | before_ids:
        actual = {r[0] for r in conn.execute('SELECT photo_path FROM photo_stack_members WHERE stack_id=? AND owner=?', (stack_id, owner))}
        if not actual.issubset(paths):
            raise StackError()
    revision = stamp(conn, owner, paths)
    for stack_id in current_ids:
        write(conn, owner, stack_id, [], None, revision)
    for stack_id in before_ids:
        members = sorted((c for c in changes if c['before'] and c['before'][0] == stack_id), key=lambda c: c['before'][2])
        write(conn, owner, stack_id, [c['path'] for c in members], members[0]['before'][1], revision)
