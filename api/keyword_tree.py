"""Visible explicit hierarchy definitions and counts, never a library-wide vocabulary leak."""

import json

from fastapi import HTTPException

from api.db_helpers import get_visibility_clause
from db.keyword_hierarchy import MAX_DEPTH, MAX_NODES, _ancestry, _graph


async def hierarchy_schema_available_async(conn):
    async with conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photo_keyword_nodes'") as cursor:
        return await cursor.fetchone() is not None


def keyword_tree(conn, owner):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photo_keyword_nodes'").fetchone():
        return {'nodes': []}
    visible, params = get_visibility_clause(owner)
    assignments = ('SELECT a.node_id,a.photo_path FROM photo_keyword_nodes a '
                   f'JOIN photos ON photos.path=a.photo_path WHERE {visible}')
    direct = dict(conn.execute(f'SELECT node_id,COUNT(*) FROM ({assignments}) GROUP BY node_id LIMIT ?',
                               [*params, MAX_NODES + 1]).fetchall())
    if len(direct) > MAX_NODES:
        raise HTTPException(412, 'Keyword hierarchy exceeds the supported node limit')
    if not direct:
        return {'nodes': []}
    # Only visible assignments and necessary ancestors enter memory. Definition
    # validation occurs before the recursive count, including cycle/depth checks.
    graph = _graph(conn, set(direct))
    chains = {node_id: _ancestry(graph, node_id) for node_id in graph}
    counts = dict(conn.execute(
        f'WITH RECURSIVE visible AS ({assignments}), '
        'walk(id,leaf,depth) AS ('
        'SELECT DISTINCT node_id,node_id,0 FROM visible UNION ALL '
        'SELECT k.parent_id,walk.leaf,walk.depth+1 FROM keyword_nodes k JOIN walk ON k.id=walk.id '
        'WHERE k.parent_id IS NOT NULL AND walk.depth<?) '
        'SELECT walk.id,COUNT(DISTINCT visible.photo_path) FROM walk '
        'JOIN visible ON visible.node_id=walk.leaf GROUP BY walk.id', [*params, MAX_DEPTH]).fetchall())
    nodes = [{'id': node_id, 'parent_id': node['parent_id'], 'name': node['name'],
              'segments': [item['name'] for item in chains[node_id]],
              'direct_count': direct.get(node_id, 0), 'branch_count': counts[node_id]}
             for node_id, node in graph.items()]
    nodes.sort(key=lambda node: tuple(name.casefold() for name in node['segments']))
    if len(json.dumps(nodes, ensure_ascii=True).encode()) > 8 * 1024 * 1024:
        raise HTTPException(412, 'Keyword hierarchy exceeds its response budget')
    return {'nodes': nodes}
