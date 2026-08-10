"""Sticky per-set panorama overrides.

Stored in the `photo_sequence_overrides` side table rather than as columns on
`photos`, for the same reason as `photo_scoring_overrides` and one more:
`utils.panorama.detect_panoramas` clears and rewrites `photos.sequence_*` at the
start of every pass, so a correction stored there would not survive its next
run. `utils.panorama.resolve_segments` is the single choke point that applies
them.

`sequence_kind` NULL suppresses a detected set ("this is not a panorama"); a
kind forces one ("these frames are one"). Forced members are tied together by
`override_group_key` rather than by `sequence_group_id`, which is renumbered
from 1 on every pass and would otherwise re-attach an override to an unrelated
set.
"""

from db.connection import get_connection

_UPSERT_SQL = """
    INSERT INTO photo_sequence_overrides
    (photo_path, sequence_kind, override_group_key, source, created_by)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(photo_path) DO UPDATE SET
        sequence_kind = excluded.sequence_kind,
        override_group_key = excluded.override_group_key,
        source = excluded.source,
        created_by = excluded.created_by
"""


def _resolve(db):
    """Yield a connection whether ``db`` is one already or a path/None."""
    if hasattr(db, 'execute'):
        return db, False
    return get_connection(db), True


def get_sequence_overrides(db, paths=None):
    """Return {photo_path: {'sequence_kind': str|None, 'override_group_key': str|None}}.

    Ordered by path so a caller reading a forced set gets its members in a
    stable order -- the kind of a forced set is read off its first member, and
    letting SQLite's arbitrary row order decide that made the label of a
    multi-kind key nondeterministic.
    """
    conn, owned = _resolve(db)
    try:
        sql = ("SELECT photo_path, sequence_kind, override_group_key "
               "FROM photo_sequence_overrides")
        params = []
        if paths is not None:
            if not paths:
                return {}
            sql += f" WHERE photo_path IN ({','.join('?' * len(paths))})"
            params = list(paths)
        sql += " ORDER BY photo_path"
        return {
            row[0]: {'sequence_kind': row[1], 'override_group_key': row[2]}
            for row in conn.execute(sql, params).fetchall()
        }
    finally:
        if owned:
            conn.close()


def set_sequence_overrides(db, paths, kind, group_key=None, source='user', created_by=None):
    """Record one correction across every path of a set.

    ``kind`` of None suppresses; a kind forces. ``group_key`` ties forced
    members together and defaults to the smallest path, which is stable for a
    given set of members.
    """
    if not paths:
        return 0
    conn, owned = _resolve(db)
    try:
        key = group_key if kind else None
        if kind and key is None:
            key = min(paths)
        conn.executemany(
            _UPSERT_SQL,
            [(path, kind, key, source, created_by) for path in paths])
        return len(paths)
    finally:
        if owned:
            conn.commit()
            conn.close()


def clear_sequence_overrides(db, paths):
    """Drop corrections for ``paths``, handing them back to the detector."""
    if not paths:
        return 0
    conn, owned = _resolve(db)
    try:
        cursor = conn.execute(
            f"DELETE FROM photo_sequence_overrides WHERE photo_path IN "
            f"({','.join('?' * len(paths))})", list(paths))
        return cursor.rowcount
    finally:
        if owned:
            conn.commit()
            conn.close()


def existing_group_key(db, paths):
    """The group key already attached to any of ``paths``, if there is one.

    Lets a caller extend or re-label an existing forced set instead of minting a
    fresh key from whatever subset it happened to submit -- recomputing the key
    per call let two overlapping calls write two kinds under one key.
    """
    if not paths:
        return None
    conn, owned = _resolve(db)
    try:
        row = conn.execute(
            f"SELECT override_group_key FROM photo_sequence_overrides "
            f"WHERE photo_path IN ({','.join('?' * len(paths))}) "
            f"AND override_group_key IS NOT NULL ORDER BY photo_path LIMIT 1",
            list(paths)).fetchone()
        return row[0] if row else None
    finally:
        if owned:
            conn.close()
