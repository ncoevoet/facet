"""Bounded organization snapshots and SQL revisions, independent of API connections.

Triggers observe photo-field writers (including imports and SQL tools). Private
stack mutations stamp revisions through their helpers; direct edits to stack tables
are unsupported. History is recorded by organization actions in their transaction.
"""
import json
import sqlite3
from typing import Any

FIELDS = {
    'gps': ('gps_latitude', 'gps_longitude', 'gps_manually_set'),
    'date': ('date_taken', 'date_manually_set'),
    'review': ('star_rating', 'is_favorite', 'is_rejected', 'is_kept'),
}
MAX_ENTRIES = 50
MAX_PHOTOS = 1000
MAX_BYTES = 1024 * 1024

_REVISION_SCHEMA = """CREATE TABLE IF NOT EXISTS {table} (
    path TEXT NOT NULL REFERENCES photos(path) ON UPDATE CASCADE ON DELETE CASCADE,
    kind TEXT NOT NULL, scope TEXT NOT NULL, revision INTEGER NOT NULL,
    PRIMARY KEY(path,kind,scope))"""


def _init_revisions(conn: sqlite3.Connection) -> None:
    conn.execute(_REVISION_SCHEMA.format(table='organization_revisions'))
    foreign_keys = conn.execute('PRAGMA foreign_key_list(organization_revisions)').fetchall()
    if any(row[2] == 'photos' and row[3] == 'path' and row[5] == 'CASCADE' for row in foreign_keys):
        return
    # The initial history schema blocked parent path updates. Rebuild only its
    # revision cache, preserving history and the monotonic clock. Keep trigger
    # replacement and the table copy in the caller's migration transaction.
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    triggers = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'organization_*'").fetchall()
    for (name,) in triggers:
        conn.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
    conn.execute(_REVISION_SCHEMA.format(table='organization_revisions_new'))
    conn.execute('''INSERT INTO organization_revisions_new
        SELECT r.* FROM organization_revisions r JOIN photos p ON p.path=r.path''')
    conn.execute('DROP TABLE organization_revisions')
    conn.execute('ALTER TABLE organization_revisions_new RENAME TO organization_revisions')


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS organization_clock (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)")
    # The read guard avoids taking a write lock on every current-schema startup.
    if not conn.execute('SELECT 1 FROM organization_clock').fetchone():
        conn.execute('INSERT INTO organization_clock VALUES (1,0)')
    _init_revisions(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS organization_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, kind TEXT NOT NULL,
        scope TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        payload TEXT NOT NULL CHECK(length(CAST(payload AS BLOB)) <= 1048576),
        part INTEGER NOT NULL, parts INTEGER NOT NULL, reverted INTEGER NOT NULL DEFAULT 0)""")
    conn.execute('CREATE INDEX IF NOT EXISTS organization_history_owner ON organization_history(owner,id DESC)')
    # Direct external SQLite writers may not enable FK enforcement. Remove all
    # scopes on deletion anyway, so recreating the same path cannot reuse a revision.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_photos_delete
        AFTER DELETE ON photos BEGIN
        DELETE FROM organization_revisions WHERE path=OLD.path;
        END""")
    # REPLACE does not run DELETE triggers unless recursive_triggers is enabled.
    # Its INSERT must invalidate old private scopes as well as global revisions.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_photos_replaced
        AFTER INSERT ON photos BEGIN
        DELETE FROM organization_revisions WHERE path=NEW.path AND scope!='';
        END""")
    # An FK-off writer can leave the old key behind. Private scopes must also
    # be invalidated when a path is moved away and later reused (rename ABA).
    conn.execute("""CREATE TRIGGER IF NOT EXISTS organization_photos_path_changed
        AFTER UPDATE OF path ON photos WHEN OLD.path IS NOT NEW.path BEGIN
        DELETE FROM organization_revisions
        WHERE path=OLD.path OR (path=NEW.path AND scope!='');
        END""")
    for kind, fields in FIELDS.items():
        sources = [('photos', 'path', "''")]
        if kind == 'review':
            sources.append(('user_preferences', 'photo_path', 'NEW.user_id'))
        for table, path, scope in sources:
            update = ' OR '.join(f'OLD.{field} IS NOT NEW.{field}' for field in fields)
            for event in ('INSERT', 'UPDATE', 'DELETE'):
                # DELETE of a preference must invalidate older snapshots, including
                # delete/recreate ABA. Photo cascade must never recreate an FK child.
                if event == 'DELETE' and table == 'photos':
                    continue
                reference = 'OLD' if event == 'DELETE' else 'NEW'
                actual_scope = scope.replace('NEW.', reference + '.')
                condition = f'EXISTS(SELECT 1 FROM photos WHERE path={reference}.{path})'
                if event == 'UPDATE':
                    changed = f'OLD.path IS NOT NEW.path OR ({update})' if table == 'photos' else update
                    condition += f' AND ({changed})'
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS organization_{table}_{kind}_{event.lower()}
                    AFTER {event} ON {table} WHEN {condition} BEGIN
                    UPDATE organization_clock SET revision=revision+1 WHERE id=1;
                    INSERT INTO organization_revisions(path,kind,scope,revision)
                    VALUES ({reference}.{path},'{kind}',{actual_scope},(SELECT revision FROM organization_clock WHERE id=1))
                    ON CONFLICT(path,kind,scope) DO UPDATE SET revision=excluded.revision;
                    END""")


def snapshot(conn: sqlite3.Connection, kind: str, scope: str, paths: list[str]) -> dict[str, dict[str, Any]]:
    result = {}
    fields = FIELDS.get(kind, ())
    for start in range(0, len(paths), 400):
        chunk = paths[start:start + 400]
        marks = ','.join('?' for _ in chunk)
        if kind == 'stack':
            rows = conn.execute(f'''SELECT p.path,m.stack_id,s.cover_path,m.position FROM photos p
                LEFT JOIN photo_stack_members m ON m.photo_path=p.path AND m.owner=?
                LEFT JOIN photo_stacks s ON s.id=m.stack_id AND s.owner=m.owner
                WHERE p.path IN ({marks})''', [scope, *chunk])
            values = {r[0]: list(r[1:]) if r[1] else [] for r in rows}
        elif kind == 'review' and scope:
            columns = ','.join(f'up.{field}' for field in fields)
            rows = conn.execute(f"SELECT p.path,{columns},up.photo_path FROM photos p LEFT JOIN user_preferences up ON up.photo_path=p.path AND up.user_id=? WHERE p.path IN ({marks})", [scope, *chunk])
            values = {r[0]: list(r[1:5]) if r[5] is not None else [0, 0, 0, 0] for r in rows}
        else:
            rows = conn.execute(f"SELECT path,{','.join(fields)} FROM photos WHERE path IN ({marks})", chunk)
            values = {r[0]: list(r[1:]) for r in rows}
        revisions = {r[0]: r[1] for r in conn.execute(f"SELECT path,revision FROM organization_revisions WHERE kind=? AND scope=? AND path IN ({marks})", [kind, scope, *chunk])}
        result.update({path: {'values': value, 'revision': revisions.get(path, 0)} for path, value in values.items()})
    return result


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def record(conn: sqlite3.Connection, owner: str, kind: str, scope: str,
           before: dict[str, dict[str, Any]]) -> list[int]:
    after = snapshot(conn, kind, scope, list(before))
    present = {path: old for path, old in before.items() if path in after}
    if all(old['values'] == after[path]['values'] for path, old in present.items()):
        return []
    # Whole-stack Undo must include unchanged retained members too. A stack
    # action cannot be split: each part would restore incomplete membership.
    changes = [dict(path=path, before=old['values'], after=after[path]['values'], revision=after[path]['revision'])
               for path, old in present.items() if kind == 'stack' or old['values'] != after[path]['values']]
    # Parts preserve existing unbounded filtered-review edits. A single photo
    # that cannot be represented is rejected; the enclosing edit rolls back.
    parts: list[list[dict[str, Any]]] = []
    if kind == 'stack':
        if len(encode(changes).encode()) > MAX_BYTES:
            raise ValueError('Organization history entry is too large')
        parts.append(changes)
    else:
        part: list[dict[str, Any]] = []
        size = 2
        for change in changes:
            encoded_size = len(encode(change).encode())
            if encoded_size + 2 > MAX_BYTES:
                raise ValueError('Organization history entry is too large')
            if part and (len(part) == MAX_PHOTOS or size + encoded_size + 1 > MAX_BYTES):
                parts.append(part)
                part, size = [], 2
            size += encoded_size + bool(part)
            part.append(change)
        parts.append(part)
    entries: list[int] = []
    for index, part in enumerate(parts, 1):
        cursor = conn.execute('INSERT INTO organization_history(owner,kind,scope,payload,part,parts) VALUES (?,?,?,?,?,?)',
                     (owner, kind, scope, encode(part), index, len(parts)))
        entry_id = cursor.lastrowid
        if entry_id is None:
            raise ValueError('Organization history entry ID is unavailable')
        entries.append(entry_id)
    conn.execute('DELETE FROM organization_history WHERE owner=? AND id NOT IN (SELECT id FROM organization_history WHERE owner=? ORDER BY id DESC LIMIT ?)', (owner, owner, MAX_ENTRIES))
    return entries
