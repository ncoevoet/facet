"""Sticky per-set sequence overrides (panorama, HDR panorama, and bracket).

Stored in the `photo_sequence_overrides` side table rather than as columns on
`photos`, for the same reason as `photo_scoring_overrides` and one more:
`utils.panorama.detect_panoramas` and `utils.sequence.detect_sequences` each
clear and rewrite `photos.sequence_*` for their own kind at the start of every
pass, so a correction stored there would not survive its next run.
`utils.panorama.resolve_segments` (panorama/HDR panorama) and
`utils.sequence.resolve_runs` (bracket) are the two choke points that apply
them.

`sequence_kind` NULL suppresses a detected set ("this is not one of these");
a kind forces one ("these frames are one"). Forced members are tied together
by `override_group_key` rather than by `sequence_group_id`, which is
renumbered from 1 on every pass and would otherwise re-attach an override to
an unrelated set.
"""

import sqlite3

from db.connection import DEFAULT_DB_PATH, apply_pragmas

_UPSERT_SQL = """
    INSERT INTO photo_sequence_overrides
    (photo_path, sequence_kind, override_group_key, source, created_by, applied_at)
    VALUES (?, ?, ?, ?, ?, NULL)
    ON CONFLICT(photo_path) DO UPDATE SET
        sequence_kind = excluded.sequence_kind,
        override_group_key = excluded.override_group_key,
        source = excluded.source,
        created_by = excluded.created_by,
        applied_at = NULL
"""


def open_connection(db_path=DEFAULT_DB_PATH):
    """Open a bare connection (with standard pragmas) that the caller closes.

    ``db.connection.get_connection`` is a context manager and cannot be used
    here: these helpers hand the connection back through ``_connection_for`` and
    close it themselves in a ``finally``, so they need a real
    ``sqlite3.Connection``, not the CM object ``get_connection(...)`` returns.
    """
    conn = sqlite3.connect(db_path)
    apply_pragmas(conn)
    return conn


def _connection_for(db):
    """Return ``(connection, owned)`` whether ``db`` is one already or a path/None.

    ``owned`` says whether this call opened it, and so whether the caller must
    commit and close: a caller that passed its own connection is mid-transaction
    and committing under it would break that.
    """
    if hasattr(db, 'execute'):
        return db, False
    return open_connection(db if db is not None else DEFAULT_DB_PATH), True


def get_sequence_overrides(db, paths=None):
    """Return {photo_path: {'sequence_kind': str|None, 'override_group_key': str|None}}.

    Ordered by path so a caller reading a forced set gets its members in a
    stable order -- the kind of a forced set is read off its first member, and
    letting SQLite's arbitrary row order decide that made the label of a
    multi-kind key nondeterministic.
    """
    conn, owned = _connection_for(db)
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
    conn, owned = _connection_for(db)
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
    conn, owned = _connection_for(db)
    try:
        cursor = conn.execute(
            f"DELETE FROM photo_sequence_overrides WHERE photo_path IN "
            f"({','.join('?' * len(paths))})", list(paths))
        return cursor.rowcount
    finally:
        if owned:
            conn.commit()
            conn.close()


def count_pending_groups(root=None, conn=None, paths=None):
    """Count unapplied correction GROUPS, not rows.

    Distinct ``override_group_key`` among ``photo_sequence_overrides`` rows
    with ``applied_at IS NULL``, optionally scoped to ``root`` (reusing
    :func:`processing.xmp_export.build_root_filter` -- the same subtree filter
    the manifest export uses, so the two stay in lockstep) or to an explicit
    ``paths`` list (the viewer's already-resolved selection -- ``photo_path IN
    (...)``, chunked to respect SQLite's variable limit). ``root`` and
    ``paths`` are mutually exclusive; passing both is a caller bug. A row with
    a NULL ``override_group_key`` counts once per row (it has no group to
    dedupe against). This matches the viewer banner's own group semantics
    (``burst-culling.component.ts``'s ``pendingCorrections`` count) rather than
    a plain row count, which would overcount a multi-frame bracket/panorama.

    The scope predicate is always parenthesized before being ANDed onto the
    ``applied_at IS NULL AND override_group_key IS (NOT) NULL`` predicates --
    a bare ``AND ... OR ...`` splice would let the ``OR`` branch of a
    multi-clause scope (e.g. ``build_root_filter``'s ``path = ? OR path LIKE
    ?``) drop both surrounding predicates and count applied/grouped rows too.
    """
    if root and paths is not None:
        raise ValueError("count_pending_groups: root and paths are mutually exclusive")

    owned_conn, owned = _connection_for(conn)
    try:
        where, params = "", []
        if root:
            from processing.xmp_export import build_root_filter
            root_where, root_params = build_root_filter(root)
            scope_predicate = (root_where.removeprefix("WHERE ")
                                .replace("path =", "photo_path =")
                                .replace("path LIKE", "photo_path LIKE"))
            where = f"AND ({scope_predicate})"
            params = root_params
        elif paths is not None:
            if not paths:
                return 0
            from api.db_helpers import select_in_chunks
            grouped_keys: set = set()
            ungrouped = 0
            for (key,) in select_in_chunks(
                owned_conn,
                "SELECT override_group_key FROM photo_sequence_overrides "
                "WHERE applied_at IS NULL AND photo_path IN ({placeholders})",
                paths,
            ):
                if key is None:
                    ungrouped += 1
                else:
                    grouped_keys.add(key)
            return len(grouped_keys) + ungrouped

        grouped = owned_conn.execute(
            "SELECT COUNT(DISTINCT override_group_key) FROM photo_sequence_overrides "
            f"WHERE applied_at IS NULL AND override_group_key IS NOT NULL {where}",
            params,
        ).fetchone()[0]
        ungrouped = owned_conn.execute(
            "SELECT COUNT(*) FROM photo_sequence_overrides "
            f"WHERE applied_at IS NULL AND override_group_key IS NULL {where}",
            params,
        ).fetchone()[0]
        return grouped + ungrouped
    finally:
        if owned:
            owned_conn.close()


def existing_group_key(db, paths, kinds=None):
    """The group key already attached to any of ``paths``, if there is one.

    Lets a caller extend or re-label an existing forced set instead of minting a
    fresh key from whatever subset it happened to submit -- recomputing the key
    per call let two overlapping calls write two kinds under one key.

    ``kinds``, when given, restricts the lookup to override rows whose
    ``sequence_kind`` is one of them -- e.g. a caller marking ``bracket`` must
    never reuse a key currently held by a ``panorama``/``hdr_panorama`` row for
    the same paths (and vice versa), or a bracket mark could silently relabel
    someone else's panorama set. Panorama and HDR panorama still share one
    lookup, since relabelling plain <-> HDR on the same key is intentional.
    """
    if not paths:
        return None
    conn, owned = _connection_for(db)
    try:
        sql = (f"SELECT override_group_key FROM photo_sequence_overrides "
               f"WHERE photo_path IN ({','.join('?' * len(paths))}) "
               f"AND override_group_key IS NOT NULL")
        params = list(paths)
        if kinds:
            sql += f" AND sequence_kind IN ({','.join('?' * len(kinds))})"
            params += list(kinds)
        sql += " ORDER BY photo_path LIMIT 1"
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    finally:
        if owned:
            conn.close()
