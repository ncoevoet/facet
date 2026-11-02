"""Logical review reads for culling, including released-schema dry runs."""
from api.db_helpers import Labels, get_visibility_clause, read_labels


def training_paths(conn, keep_paths, reject_paths, user_id, excluded=()):
    """Only distinct, authorized logical photos with a chosen representation teach preferences."""
    from api import logical_reviews
    from api.db_helpers import select_in_chunks
    from utils.panorama import PANORAMA, HDR_PANORAMA
    from utils.sequence import BRACKET
    protected_kinds = (BRACKET, PANORAMA, HDR_PANORAMA)
    keep, reject, excluded = set(keep_paths), set(reject_paths), set(excluded)
    visibility, params = get_visibility_clause(user_id)
    visible_rows = select_in_chunks(conn,
        f'SELECT photos.path,photos.sequence_kind FROM photos WHERE photos.path IN ({{placeholders}}) AND ({visibility})',
        keep | reject, after=params)
    visible = set()
    for path, kind in visible_rows:
        visible.add(path)
        if kind in protected_kinds:
            excluded.add(path)
    keep, reject = keep & visible, reject & visible
    if not has_groups(conn):
        overlap = keep & reject
        return sorted(keep - excluded - overlap), sorted(reject - excluded - overlap)
    members = dict(select_in_chunks(conn,
        'SELECT photo_path,asset_id FROM logical_asset_members WHERE photo_path IN ({placeholders})',
        keep | reject | excluded))
    excluded_assets = {members[path] for path in excluded if path in members}
    primaries = {}
    for key in sorted({members[path] for path in keep | reject if path in members} - excluded_assets):
        logical_reviews.read(conn, key, user_id)
        if conn.execute('SELECT 1 FROM logical_asset_members m JOIN photos p ON p.path=m.photo_path '
                        'WHERE m.asset_id=? AND p.sequence_kind IN (?,?,?) LIMIT 1', (key, *protected_kinds)).fetchone():
            continue
        primaries[key] = conn.execute('SELECT primary_path FROM logical_assets WHERE id=?', (key,)).fetchone()[0]

    def identities(paths):
        result = {}
        for path in paths - excluded:
            key = members.get(path)
            primary = primaries.get(key) if key is not None else path
            if primary is not None:
                result[('asset', key) if key is not None else ('file', path)] = primary
        return result

    kept, rejected = identities(keep), identities(reject)
    overlap = kept.keys() & rejected.keys()
    return sorted({path for key, path in kept.items() if key not in overlap}), sorted({path for key, path in rejected.items() if key not in overlap})


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
