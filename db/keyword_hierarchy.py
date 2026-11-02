"""Explicit semantic keyword paths, independent of literal flat manual tags.

Stable node IDs survive rename/move; direct photo assignments never imply an
assignment to ancestors. Callers own authorization/transactions. Structural
edits additionally require an explicit writable set covering every affected
photo, so a shared definition cannot partially rename hidden assignments.
"""

from contextlib import contextmanager
import hashlib
import json
import re
import unicodedata
from uuid import UUID, uuid4

MAX_DEPTH = 16
MAX_PATH_LENGTH = 1024
MAX_NODES = 20000
MAX_ASSIGNMENTS = 50
_UNCHANGED = object()


class HierarchyError(ValueError):
    """A hierarchy operation cannot safely preserve its identity contract."""


def keyword_node_id(value):
    if value == '':
        return ''
    if not isinstance(value, str):
        raise HierarchyError('Keyword branch must be a node identity')
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HierarchyError('Keyword branch must be a node identity') from exc


def create_keyword_hierarchy_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS keyword_nodes (
        id TEXT PRIMARY KEY, parent_id TEXT REFERENCES keyword_nodes(id) ON DELETE RESTRICT,
        name TEXT NOT NULL, name_key TEXT NOT NULL,
        CHECK(parent_id IS NULL OR parent_id != id))''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS keyword_nodes_siblings '
                 'ON keyword_nodes(COALESCE(parent_id,\'\'),name_key)')
    conn.execute('''CREATE TABLE IF NOT EXISTS photo_keyword_nodes (
        photo_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE ON UPDATE CASCADE,
        node_id TEXT NOT NULL REFERENCES keyword_nodes(id) ON DELETE RESTRICT,
        source TEXT NOT NULL CHECK(source IN ('user','xmp','catalog')),
        origin_source TEXT CHECK(origin_source IN ('user','xmp')),
        created_by TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        imported_path TEXT, imported_signature TEXT,
        PRIMARY KEY(photo_path,node_id))''')
    conn.execute('CREATE INDEX IF NOT EXISTS photo_keyword_nodes_node ON photo_keyword_nodes(node_id,photo_path)')
    conn.execute('''CREATE TABLE IF NOT EXISTS keyword_assignment_deletions (
        photo_path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE ON UPDATE CASCADE,
        path_key TEXT NOT NULL, node_id TEXT, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY(photo_path,path_key))''')
    # Additive updates for a database initialized by an earlier build.
    for table, column, definition in [('photo_keyword_nodes', 'origin_source', "TEXT CHECK(origin_source IN ('user','xmp'))"),
                                      ('keyword_assignment_deletions', 'node_id', 'TEXT')]:
        if column not in {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS keyword_node_edits (
        node_id TEXT PRIMARY KEY, action TEXT NOT NULL CHECK(action IN ('edit','delete')),
        changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS keyword_node_baselines (
        node_id TEXT PRIMARY KEY, signature TEXT NOT NULL)''')
    # Maintenance/relink callers also use connections without FK enforcement.
    conn.execute('''CREATE TRIGGER IF NOT EXISTS keyword_photo_delete AFTER DELETE ON photos
        BEGIN DELETE FROM photo_keyword_nodes WHERE photo_path=OLD.path;
        DELETE FROM keyword_assignment_deletions WHERE photo_path=OLD.path; END''')
    conn.execute('''CREATE TRIGGER IF NOT EXISTS keyword_photo_move AFTER UPDATE OF path ON photos
        BEGIN UPDATE photo_keyword_nodes SET photo_path=NEW.path WHERE photo_path=OLD.path;
        UPDATE keyword_assignment_deletions SET photo_path=NEW.path WHERE photo_path=OLD.path; END''')


@contextmanager
def _atomic(conn):
    name = 'keywords_' + uuid4().hex
    conn.execute('SAVEPOINT ' + name)
    try:
        yield
        conn.execute('RELEASE ' + name)
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK TO ' + name)
            conn.execute('RELEASE ' + name)
        raise


def normalize_segment(value):
    if not isinstance(value, str):
        raise HierarchyError('A keyword segment must be text')
    name = unicodedata.normalize('NFC', value)
    if any(unicodedata.category(char) in {'Cc', 'Cf'} for char in name):
        raise HierarchyError('A keyword segment cannot contain control or format characters')
    name = re.sub(r'\s+', ' ', name.strip())
    if not name or len(name) > 64 or '|' in name:
        raise HierarchyError('A keyword segment needs 1–64 characters without the hierarchy delimiter')
    return name


def normalize_path(segments):
    if not isinstance(segments, (list, tuple)) or not 1 <= len(segments) <= MAX_DEPTH:
        raise HierarchyError('A keyword path needs 1–16 explicit segments')
    result = [normalize_segment(segment) for segment in segments]
    if len('|'.join(result)) > MAX_PATH_LENGTH:
        raise HierarchyError('A keyword path exceeds 1024 characters')
    return result


def parse_imported_path(value):
    """Only call for the explicit LR hierarchy field, never a flat subject."""
    if not isinstance(value, str) or len(value) > MAX_PATH_LENGTH:
        raise HierarchyError('Unsupported imported hierarchy')
    return normalize_path(value.split('|'))


def _graph(conn, node_ids=None, *, schema='main'):
    if schema not in {'main', 'src'}:
        raise HierarchyError('Unsupported keyword database namespace')
    graph = {}
    pending = None if node_ids is None else set(node_ids)
    for _ in range(MAX_DEPTH + 1):
        if pending is None:
            rows = conn.execute(f'SELECT id,parent_id,name,name_key FROM {schema}.keyword_nodes LIMIT ?', (MAX_NODES + 1,)).fetchall()
        else:
            rows = []
            values = list(pending)
            for start in range(0, len(values), 500):
                chunk = values[start:start + 500]
                marks = ','.join('?' * len(chunk))
                rows.extend(conn.execute(f'SELECT id,parent_id,name,name_key FROM {schema}.keyword_nodes WHERE id IN ({marks})', chunk))
            if {row[0] for row in rows} != pending:
                raise HierarchyError('Keyword ancestry is incomplete')
        for node_id, parent, name, key in rows:
            if normalize_segment(name) != name or name.casefold() != key:
                raise HierarchyError('Keyword identity is inconsistent')
            graph[node_id] = {'id': node_id, 'parent_id': parent, 'name': name, 'name_key': key}
        if len(graph) > MAX_NODES:
            raise HierarchyError('Keyword vocabulary exceeds the supported node limit')
        if pending is None:
            return graph
        pending = {row[1] for row in rows if row[1] is not None and row[1] not in graph}
        if not pending:
            return graph
    raise HierarchyError('Keyword ancestry exceeds the supported depth')


def _ancestry(graph, node_id):
    result, seen = [], set()
    while node_id is not None:
        if node_id in seen or node_id not in graph or len(result) >= MAX_DEPTH:
            raise HierarchyError('Keyword ancestry is cyclic, incomplete or too deep')
        seen.add(node_id)
        node = graph[node_id]
        result.append(node)
        node_id = node['parent_id']
    result.reverse()
    normalize_path([node['name'] for node in result])
    return result


def _signature(chain):
    value = [[node['id'], node['name']] for node in chain]
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def _path_key(chain):
    return json.dumps([node['name_key'] for node in chain], ensure_ascii=True, separators=(',', ':'))


def ensure_path(conn, segments, *, local=True):
    names = normalize_path(segments)
    with _atomic(conn):
        parent = None
        for name in names:
            row = conn.execute('SELECT id FROM keyword_nodes WHERE parent_id IS ? AND name_key=?',
                               (parent, name.casefold())).fetchone()
            if row:
                parent = row[0]
                continue
            if conn.execute('SELECT COUNT(*) FROM keyword_nodes').fetchone()[0] >= MAX_NODES:
                raise HierarchyError('Keyword vocabulary exceeds the supported node limit')
            node_id = str(uuid4())
            conn.execute('INSERT INTO keyword_nodes(id,parent_id,name,name_key) VALUES(?,?,?,?)',
                         (node_id, parent, name, name.casefold()))
            if local:
                conn.execute("INSERT INTO keyword_node_edits(node_id,action) VALUES(?,'edit')", (node_id,))
            parent = node_id
        _ancestry(_graph(conn, [parent]), parent)
    return parent


def assign_node(conn, photo_path, node_id, *, source='user', created_by=None, imported_path=None):
    if source not in {'user', 'xmp', 'catalog'} or (imported_path is not None and source != 'xmp'):
        raise HierarchyError('Unsupported keyword assignment origin')
    with _atomic(conn):
        chain = _ancestry(_graph(conn, [node_id]), node_id)
        signature = None
        if imported_path is not None:
            names = parse_imported_path(imported_path)
            if [name.casefold() for name in names] != [node['name_key'] for node in chain]:
                raise HierarchyError('Imported hierarchy does not identify this node')
            signature = _signature(chain)
        if not conn.execute('SELECT 1 FROM photos WHERE path=?', (photo_path,)).fetchone():
            raise HierarchyError('Photo not found')
        key = _path_key(chain)
        deleted = conn.execute('SELECT 1 FROM keyword_assignment_deletions WHERE photo_path=? AND (path_key=? OR node_id=?)',
                               (photo_path, key, node_id)).fetchone()
        if deleted and source != 'user':
            return False
        if source == 'user':
            conn.execute('DELETE FROM keyword_assignment_deletions WHERE photo_path=? AND path_key=?', (photo_path, key))
            # Reassigning the current concept does not reinstate its old names.
            conn.execute('UPDATE keyword_assignment_deletions SET node_id=NULL WHERE photo_path=? AND node_id=?', (photo_path, node_id))
        existing = conn.execute('SELECT source,imported_path,imported_signature FROM photo_keyword_nodes '
                                'WHERE photo_path=? AND node_id=?', (photo_path, node_id)).fetchone()
        if existing:
            if existing[0] == 'user' or (source == existing[0] and imported_path == existing[1] and signature == existing[2]):
                return False
            conn.execute('UPDATE photo_keyword_nodes SET source=?,origin_source=NULL,created_by=?,imported_path=?,imported_signature=?, '
                         "created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE photo_path=? AND node_id=?",
                         (source, created_by, imported_path, signature, photo_path, node_id))
            return True
        count = conn.execute('SELECT COUNT(*) FROM photo_keyword_nodes WHERE photo_path=?', (photo_path,)).fetchone()[0]
        if count >= MAX_ASSIGNMENTS:
            raise HierarchyError('A photo can carry at most 50 directly assigned hierarchy nodes')
        conn.execute('INSERT INTO photo_keyword_nodes(photo_path,node_id,source,created_by,imported_path,imported_signature) '
                     'VALUES(?,?,?,?,?,?)', (photo_path, node_id, source, created_by, imported_path, signature))
    return True


def assign_path(conn, photo_path, segments, *, source='user', created_by=None, imported_path=None):
    with _atomic(conn):
        node_id = ensure_path(conn, segments, local=source == 'user')
        changed = assign_node(conn, photo_path, node_id, source=source, created_by=created_by, imported_path=imported_path)
    return node_id, changed


def photo_hierarchies(conn, photo_path):
    """Read old schemas without migrating; no invented hierarchy from flat tags."""
    return load_hierarchy_map(conn, [photo_path]).get(photo_path, [])


def plan_path_import(conn, photo_path, paths, *, pending_prefixes=None):
    """Read-only additive import plan, also valid on released schemas.

    Do not create speculative nodes for protected removals. The caller applies
    this plan under its writer transaction; previews never allocate identities.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    supported = 'photo_keyword_nodes' in tables
    current = photo_hierarchies(conn, photo_path) if supported else []
    assigned = {tuple(name.casefold() for name in item['segments']): item for item in current}
    tombstones = list(conn.execute('SELECT path_key,node_id FROM keyword_assignment_deletions WHERE photo_path=?',
                                   (photo_path,))) if supported else []
    deleted_paths = {row[0] for row in tombstones}
    deleted_ids = {row[1] for row in tombstones if row[1] is not None}
    new_prefixes, seen, proposed, diagnostics = set(), set(), [], []
    added = 0
    for raw in paths:
        try:
            names = parse_imported_path(raw)
        except HierarchyError as exc:
            diagnostics.append({'field': 'hierarchy', 'value': raw, 'reason': 'invalid_hierarchy', 'detail': str(exc)})
            continue
        key = tuple(name.casefold() for name in names)
        if key in seen:
            continue
        seen.add(key)
        node_id, candidate_prefixes = None, set()
        missing = not supported
        for index, name in enumerate(names):
            row = None if missing else conn.execute('SELECT id FROM keyword_nodes WHERE parent_id IS ? AND name_key=?',
                                                    (node_id, name.casefold())).fetchone()
            if row is None:
                missing = True
                candidate_prefixes.add(key[:index + 1])
            else:
                node_id = row[0]
        path_key = json.dumps(key, ensure_ascii=True, separators=(',', ':'))
        existing = assigned.get(key)
        if path_key in deleted_paths or (not missing and node_id in deleted_ids) or (existing and existing['source'] == 'user'):
            diagnostics.append({'field': 'hierarchy', 'value': raw, 'reason': 'local_hierarchy_edit'})
            continue
        if existing and existing['source'] == 'xmp' and existing['exported_path'] == raw:
            continue
        if not existing:
            added += 1
        # Count only missing prefixes of accepted paths, shared across siblings.
        new_prefixes.update(candidate_prefixes)
        proposed.append((names, raw))
    node_count = conn.execute('SELECT COUNT(*) FROM keyword_nodes').fetchone()[0] if supported else 0
    projected = new_prefixes | (pending_prefixes or set())
    if len(current) + added > MAX_ASSIGNMENTS or node_count + len(projected) > MAX_NODES:
        diagnostics.append({'field': 'hierarchy', 'reason': 'hierarchy_cap', 'proposed': len(proposed)})
        return [], diagnostics
    if pending_prefixes is not None:
        pending_prefixes.update(new_prefixes)
    return proposed, diagnostics


def load_hierarchy_map(conn, photo_paths, *, max_bytes=8 * 1024 * 1024):
    """Materialize only requested assignments and their ancestors, in chunks.

    Callers authorize photo paths first. API callers retain a bounded response
    budget; CLI exports may opt out while passing a bounded photo chunk.
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photo_keyword_nodes'").fetchone():
        return {}
    paths = list(dict.fromkeys(photo_paths))
    result, size = {}, 0
    for start in range(0, len(paths), 500):
        chunk = paths[start:start + 500]
        marks = ','.join('?' * len(chunk))
        rows = conn.execute('SELECT photo_path,node_id,source,imported_path,imported_signature '
                            f'FROM photo_keyword_nodes WHERE photo_path IN ({marks}) ORDER BY photo_path,node_id LIMIT ?',
                            [*chunk, len(chunk) * MAX_ASSIGNMENTS + 1]).fetchall()
        if len(rows) > len(chunk) * MAX_ASSIGNMENTS:
            raise HierarchyError('Stored keyword assignments exceed their supported limit')
        graph = _graph(conn, {row[1] for row in rows})
        for path, node_id, source, imported, signature in rows:
            assigned = result.setdefault(path, [])
            if len(assigned) >= MAX_ASSIGNMENTS:
                raise HierarchyError('Stored keyword assignments exceed their supported limit')
            chain = _ancestry(graph, node_id)
            names = [node['name'] for node in chain]
            exported = imported if imported is not None and signature == _signature(chain) else '|'.join(names)
            item = {'node_id': node_id, 'segments': names, 'source': source, 'exported_path': exported}
            size += len(json.dumps(item, ensure_ascii=True).encode())
            if max_bytes is not None and size > max_bytes:
                raise HierarchyError('Keyword hierarchy preview exceeds its response budget')
            assigned.append(item)
    for assigned in result.values():
        assigned.sort(key=lambda item: (item['exported_path'].casefold(), item['node_id']))
    return result


def _subtree(graph, node_id):
    if node_id not in graph:
        raise HierarchyError('Keyword node not found')
    children = {}
    for node in graph.values():
        children.setdefault(node['parent_id'], []).append(node['id'])
    found, pending = set(), [node_id]
    while pending:
        current = pending.pop()
        if current in found:
            raise HierarchyError('Keyword hierarchy contains a cycle')
        found.add(current)
        pending.extend(children.get(current, []))
    return found


def _affected_paths(conn, nodes, writable_paths):
    if not isinstance(writable_paths, (set, frozenset)):
        raise HierarchyError('Structural edits require an explicit current writable-photo set')
    affected = set()
    values = sorted(nodes)
    for start in range(0, len(values), 500):
        chunk = values[start:start + 500]
        marks = ','.join('?' * len(chunk))
        affected.update(row[0] for row in conn.execute(
            f'SELECT DISTINCT photo_path FROM photo_keyword_nodes WHERE node_id IN ({marks})', chunk))
    if not affected.issubset(writable_paths):
        raise HierarchyError('The complete branch cannot be changed in the current writable scope')
    return sorted(affected)


def change_node(conn, node_id, *, writable_paths, name=None, parent_id=_UNCHANGED, created_by=None):
    with _atomic(conn):
        graph = _graph(conn)
        branch = _subtree(graph, node_id)
        node = graph[node_id]
        label = normalize_segment(name) if name is not None else node['name']
        parent = node['parent_id'] if parent_id is _UNCHANGED else parent_id
        if parent in branch or (parent is not None and parent not in graph):
            raise HierarchyError('A node cannot move into its branch or a missing parent')
        if any(other['id'] != node_id and other['parent_id'] == parent and other['name_key'] == label.casefold()
               for other in graph.values()):
            raise HierarchyError('The destination already contains that keyword')
        if label == node['name'] and parent == node['parent_id']:
            return []
        affected = _affected_paths(conn, branch, writable_paths)
        old_keys = {descendant: _path_key(_ancestry(graph, descendant)) for descendant in branch}
        graph[node_id] = {**node, 'parent_id': parent, 'name': label, 'name_key': label.casefold()}
        for descendant in branch:
            _ancestry(graph, descendant)
        conn.execute('UPDATE keyword_nodes SET parent_id=?,name=?,name_key=? WHERE id=?', (parent, label, label.casefold(), node_id))
        conn.execute("INSERT INTO keyword_node_edits(node_id,action) VALUES(?,'edit') "
                     "ON CONFLICT(node_id) DO UPDATE SET action='edit',changed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')", (node_id,))
        for descendant in branch:
            conn.execute('INSERT OR IGNORE INTO keyword_assignment_deletions(photo_path,path_key,node_id) '
                         'SELECT photo_path,?,node_id FROM photo_keyword_nodes WHERE node_id=?', (old_keys[descendant], descendant))
            conn.execute('UPDATE photo_keyword_nodes SET source=\'user\',origin_source=NULL,created_by=?,imported_path=NULL,imported_signature=NULL, '
                         "created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE node_id=?", (created_by, descendant))
    return affected


def remove_assignment(conn, photo_path, node_id):
    with _atomic(conn):
        if not conn.execute('SELECT 1 FROM photo_keyword_nodes WHERE photo_path=? AND node_id=?', (photo_path, node_id)).fetchone():
            return False
        key = _path_key(_ancestry(_graph(conn, [node_id]), node_id))
        conn.execute('INSERT OR IGNORE INTO keyword_assignment_deletions(photo_path,path_key,node_id) VALUES(?,?,?)', (photo_path, key, node_id))
        conn.execute('DELETE FROM photo_keyword_nodes WHERE photo_path=? AND node_id=?', (photo_path, node_id))
    return True


def delete_branch(conn, node_id, *, writable_paths):
    with _atomic(conn):
        graph = _graph(conn)
        branch = _subtree(graph, node_id)
        affected = _affected_paths(conn, branch, writable_paths)
        for descendant in sorted(branch, key=lambda value: len(_ancestry(graph, value)), reverse=True):
            key = _path_key(_ancestry(graph, descendant))
            conn.execute('INSERT OR IGNORE INTO keyword_assignment_deletions(photo_path,path_key,node_id) '
                         'SELECT photo_path,?,node_id FROM photo_keyword_nodes WHERE node_id=?', (key, descendant))
            conn.execute("INSERT INTO keyword_node_edits(node_id,action) VALUES(?,'delete') "
                         "ON CONFLICT(node_id) DO UPDATE SET action='delete',changed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')", (descendant,))
            conn.execute('DELETE FROM photo_keyword_nodes WHERE node_id=?', (descendant,))
            conn.execute('DELETE FROM keyword_nodes WHERE id=?', (descendant,))
    return affected
