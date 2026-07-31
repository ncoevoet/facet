"""Sticky per-photo scoring context and category override lookups.

Stored in the `photo_scoring_overrides` side table rather than as columns on
`photos`, because `save_photo`/`save_photos_batch` write photos via
INSERT OR REPLACE (processing/scorer.py), which would silently wipe any new
column on that row on the next rescan. `processing.scorer.Facet.
_determine_photo_category` is the single choke point that reads these
overrides.
"""

from db.connection import get_connection, DEFAULT_DB_PATH

_CLEARABLE_FIELDS = ('scoring_context', 'category_override')

_SELECT_SQL = "SELECT photo_path, scoring_context, category_override FROM photo_scoring_overrides"

_UPSERT_SQL = """
    INSERT INTO photo_scoring_overrides
    (photo_path, scoring_context, category_override, source, created_by)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(photo_path) DO UPDATE SET
        scoring_context = COALESCE(excluded.scoring_context, photo_scoring_overrides.scoring_context),
        category_override = COALESCE(excluded.category_override, photo_scoring_overrides.category_override),
        source = COALESCE(excluded.source, photo_scoring_overrides.source),
        created_by = COALESCE(excluded.created_by, photo_scoring_overrides.created_by)
"""

_CLEANUP_SQL = (
    "DELETE FROM photo_scoring_overrides "
    "WHERE photo_path = ? AND scoring_context IS NULL AND category_override IS NULL"
)


def get_photo_scoring_overrides(db, paths=None):
    """Return {photo_path: {'scoring_context': str|None, 'category_override': str|None}}.

    ``db`` may be an open sqlite3 connection or a database path / None (a
    short-lived connection is opened here). ``paths`` restricts the lookup to
    the given photo paths in a single query; omit it to load every override
    row (the whole-library recompute path). Callers batch this lookup once
    per chunk/scan rather than querying per photo.
    """
    query = _SELECT_SQL
    params = ()
    if paths is not None:
        paths = list(paths)
        if not paths:
            return {}
        placeholders = ','.join('?' * len(paths))
        query = f"{_SELECT_SQL} WHERE photo_path IN ({placeholders})"
        params = tuple(paths)

    if hasattr(db, 'execute'):
        rows = db.execute(query, params).fetchall()
    else:
        with get_connection(db or DEFAULT_DB_PATH) as conn:
            rows = conn.execute(query, params).fetchall()

    return {
        photo_path: {'scoring_context': scoring_context, 'category_override': category_override}
        for photo_path, scoring_context, category_override in rows
    }


def set_photo_scoring_override(db, path, *, scoring_context=None, category_override=None,
                               source=None, created_by=None):
    """Upsert a photo's scoring context and/or category override.

    Only the fields passed as non-None are written; an unset field leaves any
    existing value untouched, so an album-level scoring_context and the
    per-photo category_override escape hatch can be set independently of
    each other. ``db`` may be an open sqlite3 connection (the caller owns the
    commit) or a database path / None (a short-lived connection is opened and
    committed here).
    """
    params = (path, scoring_context, category_override, source, created_by)
    if hasattr(db, 'execute'):
        db.execute(_UPSERT_SQL, params)
        return
    with get_connection(db or DEFAULT_DB_PATH) as conn:
        conn.execute(_UPSERT_SQL, params)
        conn.commit()


def clear_photo_scoring_override(db, path, *, field):
    """Clear one override field, deleting the row once both fields are NULL.

    ``field`` must be 'scoring_context' or 'category_override'. ``db`` may be
    an open sqlite3 connection (the caller owns the commit) or a database
    path / None (a short-lived connection is opened and committed here).
    """
    if field not in _CLEARABLE_FIELDS:
        raise ValueError(f"field must be one of {_CLEARABLE_FIELDS}, got {field!r}")
    update_sql = f"UPDATE photo_scoring_overrides SET {field} = NULL WHERE photo_path = ?"
    if hasattr(db, 'execute'):
        db.execute(update_sql, (path,))
        db.execute(_CLEANUP_SQL, (path,))
        return
    with get_connection(db or DEFAULT_DB_PATH) as conn:
        conn.execute(update_sql, (path,))
        conn.execute(_CLEANUP_SQL, (path,))
        conn.commit()
