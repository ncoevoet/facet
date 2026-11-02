"""Logical review reads for culling, including released-schema dry runs."""
from api.db_helpers import Labels, get_visibility_clause, read_labels


def has_groups(conn):
    # Released read-only catalogs may predate logical photos entirely.
    return (conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='logical_assets'").fetchone() is not None
            and conn.execute('SELECT 1 FROM logical_assets LIMIT 1').fetchone() is not None)


def standalone_source(conn, user_id):
    if not has_groups(conn):
        return None
    from api.config import is_multi_user_enabled
    from api.logical_collection import source
    visibility, params = get_visibility_clause(user_id)
    personal = is_multi_user_enabled()
    columns = ['path', 'star_rating', 'is_favorite', 'is_rejected', 'is_kept',
               'aggregate', 'sequence_kind', 'similarity_reviewed', 'burst_group_id']
    return source(columns, owner=(user_id or '') if personal else '',
                  multi_user=personal, visibility_sql=visibility, visibility_params=params)


def read_culling_labels(conn, user_id, paths, *, include_kept=False):
    from api import logical_export
    paths = list(paths)
    owned = not conn.in_transaction
    if owned:
        conn.execute('BEGIN')
    try:
        labels = read_labels(conn, user_id, paths, include_kept=include_kept)
        if has_groups(conn):
            rows = {path: {'path': path} for path in paths}
            logical_export.attach(conn, rows, user_id)
            for path, row in rows.items():
                if '_logical_review' in row:
                    labels[path] = Labels(row['star_rating'] or 0, row['is_favorite'] or 0,
                                         row['is_rejected'] or 0, (row['is_kept'] or 0) if include_kept else 0)
        return labels
    finally:
        if owned:
            conn.rollback()


def authority_snapshot(conn, user_id, paths):
    """Private revision bindings for the preview digest, in its label snapshot."""
    from api import logical_export
    if not has_groups(conn):
        return []
    rows = {path: {'path': path} for path in paths}
    logical_export.attach(conn, rows, user_id)
    guards = {guard['asset_id']: guard for row in rows.values() if (guard := logical_export.guard(row)) is not None}
    return [guards[key] for key in sorted(guards)]
