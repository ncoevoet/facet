"""Bounded organization snapshots and SQL revisions, independent of API connections.

Triggers observe every writer (including imports and SQL tools). History itself is
explicitly recorded only by organization actions, in their existing transaction.
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


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS organization_clock (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)")
    # The read guard avoids taking a write lock on every current-schema startup.
    if not conn.execute('SELECT 1 FROM organization_clock').fetchone():
        conn.execute('INSERT INTO organization_clock VALUES (1,0)')
    conn.execute("""CREATE TABLE IF NOT EXISTS organization_revisions (
        path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE,
        kind TEXT NOT NULL, scope TEXT NOT NULL, revision INTEGER NOT NULL,
        PRIMARY KEY(path,kind,scope))""")
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
                    condition += f' AND ({update})'
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS organization_{table}_{kind}_{event.lower()}
                    AFTER {event} ON {table} WHEN {condition} BEGIN
                    UPDATE organization_clock SET revision=revision+1 WHERE id=1;
                    INSERT INTO organization_revisions(path,kind,scope,revision)
                    VALUES ({reference}.{path},'{kind}',{actual_scope},(SELECT revision FROM organization_clock WHERE id=1))
                    ON CONFLICT(path,kind,scope) DO UPDATE SET revision=excluded.revision;
                    END""")


def snapshot(conn: sqlite3.Connection, kind: str, scope: str, paths: list[str]) -> dict[str, dict[str, Any]]:
    result = {}
    fields = FIELDS[kind]
    for start in range(0, len(paths), 400):
        chunk = paths[start:start + 400]
        marks = ','.join('?' for _ in chunk)
        if kind == 'review' and scope:
            columns = ','.join(f'up.{field}' for field in fields)
            rows = conn.execute(f"SELECT p.path,{columns},up.photo_path FROM photos p LEFT JOIN user_preferences up ON up.photo_path=p.path AND up.user_id=? WHERE p.path IN ({marks})", [scope, *chunk])
            values = {r[0]: list(r[1:5]) if r[5] is not None else [0, 0, 0, 0] for r in rows}
        else:
            rows = conn.execute(f"SELECT path,{','.join(fields)} FROM photos WHERE path IN ({marks})", chunk)
            values = {r[0]: list(r[1:]) for r in rows}
        revisions = {r[0]: r[1] for r in conn.execute(f"SELECT path,revision FROM organization_revisions WHERE kind=? AND scope=? AND path IN ({marks})", [kind, scope, *chunk])}
        result.update({path: {'values': value, 'revision': revisions.get(path, 0)} for path, value in values.items()})
    return result


def record(conn: sqlite3.Connection, owner: str, kind: str, scope: str,
           before: dict[str, dict[str, Any]]) -> None:
    after = snapshot(conn, kind, scope, list(before))
    changes = [dict(path=path, before=old['values'], after=after[path]['values'], revision=after[path]['revision'])
               for path, old in before.items() if path in after and old['values'] != after[path]['values']]
    if not changes:
        return
    # Parts preserve existing unbounded filtered-review edits. A single photo
    # that cannot be represented is rejected; the enclosing edit rolls back.
    parts: list[list[dict[str, Any]]] = []
    part: list[dict[str, Any]] = []
    size = 2
    for change in changes:
        encoded_size = len(json.dumps(change, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode())
        if encoded_size + 2 > MAX_BYTES:
            raise ValueError('Organization history entry is too large')
        if part and (len(part) == MAX_PHOTOS or size + encoded_size + 1 > MAX_BYTES):
            parts.append(part)
            part, size = [], 2
        size += encoded_size + bool(part)
        part.append(change)
    parts.append(part)
    for index, part in enumerate(parts, 1):
        conn.execute('INSERT INTO organization_history(owner,kind,scope,payload,part,parts) VALUES (?,?,?,?,?,?)',
                     (owner, kind, scope, json.dumps(part, ensure_ascii=True, separators=(',', ':'), allow_nan=False), index, len(parts)))
    conn.execute('DELETE FROM organization_history WHERE owner=? AND id NOT IN (SELECT id FROM organization_history WHERE owner=? ORDER BY id DESC LIMIT ?)', (owner, owner, MAX_ENTRIES))
