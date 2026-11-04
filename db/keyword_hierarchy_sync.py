"""Viewer export boundaries for shared taxonomy and destination-local intent.

Definitions/assignments are durable catalog metadata. Local edit, deletion and
replication receipts are authority belonging to one database, not source edits
to replay on a viewer. A temporary source snapshot spans the existing export's
separate metadata phases; only the hierarchy merge itself is atomic.
"""

from dataclasses import dataclass
import hashlib
import json
from uuid import uuid4

from db.transactions import savepoint
from db.keyword_hierarchy import (
    HierarchyError, MAX_ASSIGNMENTS, MAX_NODES, _ancestry, _graph,
    _path_key, create_keyword_hierarchy_schema,
)


def _exists(conn, schema, table):
    return conn.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _signature(node):
    return hashlib.sha256(json.dumps([node['id'], node['parent_id'], node['name'], node['name_key']],
                                     ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()


def reset_viewer_hierarchy_authority(conn):
    """On a fresh copied DB, retain values/origins but mint no local authority."""
    if not _exists(conn, 'main', 'keyword_nodes') and not _exists(conn, 'main', 'photo_keyword_nodes'):
        return
    create_keyword_hierarchy_schema(conn)
    with savepoint(conn):
        graph = _graph(conn)
        for node_id in graph:
            _ancestry(graph, node_id)
        conn.execute("UPDATE photo_keyword_nodes SET origin_source=CASE WHEN source IN ('user','xmp') THEN source ELSE origin_source END, "
                     "source='catalog',created_by=NULL")
        conn.execute('DELETE FROM keyword_assignment_deletions')
        conn.execute('DELETE FROM keyword_node_edits')
        conn.execute('DELETE FROM keyword_node_baselines')
        conn.executemany('INSERT INTO keyword_node_baselines(node_id,signature) VALUES(?,?)',
                         [(node_id, _signature(node)) for node_id, node in graph.items()])


def _propose(conn, source):
    current = _graph(conn)
    edits = dict(conn.execute('SELECT node_id,action FROM keyword_node_edits'))
    baselines = dict(conn.execute('SELECT node_id,signature FROM keyword_node_baselines'))
    proposed, copied = dict(current), set()
    allowed = set()
    for node_id in source:
        chain = _ancestry(source, node_id)
        if any(edits.get(node['id']) == 'delete' for node in chain):
            continue
        allowed.add(node_id)
        node = current.get(node_id)
        if node_id not in edits and (node is None or baselines.get(node_id) == _signature(node)):
            proposed[node_id] = source[node_id]
            copied.add(node_id)
    local_assignments = {row[0] for row in conn.execute("SELECT DISTINCT node_id FROM photo_keyword_nodes WHERE source!='catalog'")}
    deleted = {node_id for node_id, node in current.items()
               if node_id not in source and node_id not in edits and node_id not in local_assignments
               and baselines.get(node_id) == _signature(node)}
    # A locally retained descendant needs its ancestors even if the source has
    # removed them. Retain only ancestors in the proposed final graph.
    for node_id in proposed.keys() - deleted:
        deleted.difference_update(node['id'] for node in _ancestry(proposed, node_id))
    for node_id in deleted:
        del proposed[node_id]
    if len(proposed) > MAX_NODES:
        raise HierarchyError('Merged keyword vocabulary exceeds its node limit')
    siblings = set()
    for node_id, node in proposed.items():
        _ancestry(proposed, node_id)
        key = node['parent_id'], node['name_key']
        if key in siblings:
            raise HierarchyError('Source and viewer keyword definitions conflict; resolve their identities before refreshing')
        siblings.add(key)
    return current, proposed, copied, allowed


@dataclass
class HierarchySync:
    source: dict
    assignments: str
    mapping: str

    def close(self, conn):
        conn.execute(f'DROP TABLE IF EXISTS temp.{self.mapping}')
        conn.execute(f'DROP TABLE IF EXISTS temp.{self.assignments}')

    def _mapping(self, conn, proposed, allowed):
        conn.execute(f'DELETE FROM temp.{self.mapping}')
        conn.executemany(f'INSERT INTO temp.{self.mapping}(node_id,path_key) VALUES(?,?)',
                         [(node_id, _path_key(_ancestry(proposed, node_id))) for node_id in allowed])

    def _incoming(self):
        return (f'FROM temp.{self.assignments} s JOIN temp.{self.mapping} k ON k.node_id=s.node_id '
                'WHERE NOT EXISTS(SELECT 1 FROM keyword_assignment_deletions d '
                'WHERE d.photo_path=s.photo_path AND (d.path_key=k.path_key OR d.node_id=s.node_id))')

    def _check_capacity(self, conn):
        excess = conn.execute(
            'SELECT photo_path FROM (SELECT photo_path,node_id FROM photo_keyword_nodes WHERE source!=\'catalog\' '
            'UNION SELECT s.photo_path,s.node_id ' + self._incoming() + ') '
            'GROUP BY photo_path HAVING COUNT(*)>? LIMIT 1', (MAX_ASSIGNMENTS,)).fetchone()
        if excess:
            raise HierarchyError('Merged keyword assignments exceed the per-photo limit')

    def preflight(self, conn):
        _, proposed, _, allowed = _propose(conn, self.source)
        self._mapping(conn, proposed, allowed)
        self._check_capacity(conn)

    def apply(self, conn):
        """Re-read destination edits immediately before this atomic merge."""
        with savepoint(conn):
            current, proposed, copied, allowed = _propose(conn, self.source)
            self._mapping(conn, proposed, allowed)
            self._check_capacity(conn)
            changed = {node_id for node_id in copied if current.get(node_id) != proposed[node_id]}
            # A valid final graph may swap sibling names/positions. Reserve
            # unreachable normalization keys until all final identities fit.
            prefix = '\0facet-sync-' + uuid4().hex
            removed = current.keys() - proposed.keys()
            for node_id in (changed & current.keys()) | removed:
                conn.execute('UPDATE keyword_nodes SET name_key=? WHERE id=?', (prefix + node_id, node_id))
            for node_id in sorted(changed - current.keys(), key=lambda value: len(_ancestry(proposed, value))):
                node = proposed[node_id]
                conn.execute('INSERT INTO keyword_nodes(id,parent_id,name,name_key) VALUES(?,?,?,?)',
                             (node_id, node['parent_id'], node['name'], node['name_key']))
            for node_id in changed & current.keys():
                node = proposed[node_id]
                conn.execute('UPDATE keyword_nodes SET parent_id=?,name=?,name_key=? WHERE id=?',
                             (node['parent_id'], node['name'], node['name_key'], node_id))
            # Catalog assignments are replaced below; local assignments and
            # edited descendants have already protected their ancestors.
            conn.execute("DELETE FROM photo_keyword_nodes WHERE source='catalog'")
            for node_id in sorted(removed, key=lambda value: len(_ancestry(current, value)), reverse=True):
                conn.execute('DELETE FROM keyword_nodes WHERE id=?', (node_id,))
                conn.execute('DELETE FROM keyword_node_baselines WHERE node_id=?', (node_id,))
            conn.executemany('INSERT INTO keyword_node_baselines(node_id,signature) VALUES(?,?) '
                             'ON CONFLICT(node_id) DO UPDATE SET signature=excluded.signature',
                             [(node_id, _signature(proposed[node_id])) for node_id in copied])
            # Only baseline rows mirror the source. Local user/import edits and
            # deletion intent survive even if the scanner no longer has them.
            conn.execute(
                'INSERT INTO photo_keyword_nodes '
                '(photo_path,node_id,source,origin_source,created_at,imported_path,imported_signature) '
                "SELECT s.photo_path,s.node_id,'catalog',CASE WHEN s.source IN ('user','xmp') THEN s.source ELSE s.origin_source END, "
                's.created_at,s.imported_path,s.imported_signature ' + self._incoming()
                + ' AND EXISTS(SELECT 1 FROM photos p WHERE p.path=s.photo_path) '
                'ON CONFLICT(photo_path,node_id) DO NOTHING')


def prepare_hierarchy_sync(conn):
    """Capture attached ``src`` without importing its local edit receipts."""
    present = [_exists(conn, 'src', table) for table in ('keyword_nodes', 'photo_keyword_nodes')]
    if not any(present):
        return None
    if not all(present):
        raise HierarchyError('Source keyword hierarchy schema is incomplete')
    if 'origin_source' not in {row[1] for row in conn.execute('PRAGMA src.table_info(photo_keyword_nodes)')}:
        raise HierarchyError('Initialize the source keyword schema before refreshing the viewer')
    suffix = uuid4().hex
    captured = HierarchySync({}, 'keyword_source_' + suffix, 'keyword_map_' + suffix)
    try:
        with savepoint(conn):
            source = _graph(conn, schema='src')
            for node_id in source:
                _ancestry(source, node_id)
            invalid = conn.execute('SELECT 1 FROM src.photo_keyword_nodes a '
                                   'LEFT JOIN src.photos p ON p.path=a.photo_path '
                                   'LEFT JOIN src.keyword_nodes n ON n.id=a.node_id '
                                   'WHERE p.path IS NULL OR n.id IS NULL LIMIT 1').fetchone()
            if invalid:
                raise HierarchyError('Source hierarchy contains an orphan assignment')
            conn.execute(f'CREATE TEMP TABLE {captured.assignments} AS SELECT '
                         'photo_path,node_id,source,origin_source,created_at,imported_path,imported_signature FROM src.photo_keyword_nodes')
            conn.execute(f'CREATE UNIQUE INDEX {captured.assignments}_key ON {captured.assignments}(photo_path,node_id)')
            conn.execute(f'CREATE TEMP TABLE {captured.mapping}(node_id TEXT PRIMARY KEY,path_key TEXT NOT NULL)')
            captured.source = source
            captured.preflight(conn)
        return captured
    except BaseException:
        captured.close(conn)
        raise
