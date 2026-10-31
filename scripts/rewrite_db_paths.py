"""Rewrite stored photo paths in a Facet database from one prefix to another.

Built for moving a library scanned in Docker (``/data/photos/...``) to a native
install, where the scanner stores ``Path.resolve()`` paths such as
``\\\\NAS\\share\\...`` on Windows. ``viewer.path_mapping`` only covers the viewer, so
a mapped database would gain duplicate rows on the next scan; rewriting keeps the
viewer and the scanner on one spelling.

It rewrites every plain path column and the JSON columns that embed paths, drops the
stats cache, rebuilds FTS and empties ``photos_vec`` (keyed by path; repopulate it with
``python database.py --populate-vec``). Stop the viewer and any scan first: the tool
takes the library lock, which scans and maintenance jobs hold, but a running viewer
does not hold it.

    python scripts/rewrite_db_paths.py DB /data/photos "\\\\NAS\\Photos" --dry-run
    python scripts/rewrite_db_paths.py DB /data/photos "\\\\NAS\\Photos"

Safety:
- ``--dry-run`` reports what would change and writes nothing.
- Otherwise the database is first copied to ``DB.before-rewrite-<time>`` (``--no-backup``
  skips that); every change is one transaction, so a failure leaves the database as it was.
- Matching is exact and case-sensitive: a stored path changes only when it equals the old
  prefix or continues it with ``/`` or ``\\``.
- Separators: trailing ones on either prefix are ignored, and the rest of each path takes
  the new prefix's separator (``\\`` for a drive letter or a UNC path, else ``/``;
  ``--sep`` overrides).
- Prefixes where one lies inside the other (``/data/photos`` to ``/data/photos/new``) are refused
  with exit 2: rows the triggers insert during the rewrite would be converted twice. Go
  through an unrelated temporary prefix instead.
- A rewrite that would add foreign-key violations is rolled back. After commit the tool
  exits 1 if the integrity or foreign-key check fails.

Undo history recorded before the rewrite (``organization_history``) cannot be applied
afterwards: each entry is tied to its photos' revisions, which a path change advances on
purpose. The tool reports how many entries that affects.
"""
import argparse
import contextlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

JSON_COLUMNS = [('albums', 'smart_filter_json'), ('scan_runs', 'args_json')]
SEPARATORS = '/\\'


def trim(prefix):
    """``prefix`` without trailing separators; a bare root keeps one."""
    return prefix.rstrip(SEPARATORS) or prefix[:1]


def nested(a, b):
    """True when one prefix is the other or lies inside it (separators compared as one)."""
    a, b = a.replace('\\', '/'), b.replace('\\', '/')
    return a == b or a.startswith(b.rstrip('/') + '/') or b.startswith(a.rstrip('/') + '/')


def default_sep(dst):
    return '\\' if dst.startswith('\\\\') or re.match(r'^[A-Za-z]:', dst) else '/'


def convert(value, src, dst, sep):
    if not isinstance(value, str):
        return value
    if value == src:
        return dst
    if value.startswith(src) and value[len(src):len(src) + 1] in ('/', '\\'):
        return dst + re.sub(r'[\\/]', lambda _: sep, value[len(src):])
    return value


def convert_json(obj, src, dst, sep):
    if isinstance(obj, dict):
        return {k: convert_json(v, src, dst, sep) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_json(v, src, dst, sep) for v in obj]
    return convert(obj, src, dst, sep)


def under(col):
    """SQL selecting values equal to ``?1`` or continuing it with a separator (``?2`` = its length)."""
    return f'("{col}" = ?1 OR substr("{col}", 1, ?2 + 1) IN (?1 || \'/\', ?1 || \'\\\'))'


def path_columns(conn):
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND sql NOT LIKE 'CREATE VIRTUAL%' "
        "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'photos_fts_%' AND name NOT LIKE 'photos_vec_%'")]
    for table in tables:
        for col in conn.execute(f'PRAGMA table_info("{table}")'):
            name = col[1]
            if name == 'path' or name.endswith('_path'):
                yield table, name


def has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


def load_vec(conn):
    """True when sqlite-vec loads, so ``photos_vec`` can be emptied."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except Exception:
        return False


def rekey_dismissals(conn):
    """Recompute each skipped stack suggestion's key from its rewritten member paths.

    The key is a hash of the group's kind and sorted paths (``db.stack_suggestions.suggestion_key``),
    so a rewrite that leaves it alone silently brings back every suggestion the user skipped.
    """
    from db.stack_suggestions import suggestion_key
    groups = {}
    for owner, key, kind, path in conn.execute('SELECT owner, key, kind, photo_path FROM stack_suggestion_dismissals'):
        groups.setdefault((owner, key, kind), []).append(path)
    rekeyed = 0
    for (owner, key, kind), paths in groups.items():
        new = suggestion_key(kind, paths)
        if new != key:
            conn.execute('UPDATE stack_suggestion_dismissals SET key = ? WHERE owner = ? AND key = ?', (new, owner, key))
            rekeyed += 1
    return rekeyed


def rewrite(conn, src, dst, sep, vec):
    """Apply every change inside the open transaction; return the report lines."""
    report = []
    args = (src, len(src))
    for table, col in path_columns(conn):
        n = conn.execute(
            f'UPDATE "{table}" SET "{col}" = facet_rewrite("{col}") WHERE {under(col)}', args).rowcount
        if n:
            report.append(f'{table}.{col}: {n}')
    for table, col in JSON_COLUMNS:
        if not has_table(conn, table):
            continue
        changed = 0
        for rowid, raw in conn.execute(f'SELECT rowid, "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL').fetchall():
            new = json.dumps(convert_json(json.loads(raw), src, dst, sep))
            if new != json.dumps(json.loads(raw)):
                conn.execute(f'UPDATE "{table}" SET "{col}" = ? WHERE rowid = ?', (new, rowid))
                changed += 1
        if changed:
            report.append(f'{table}.{col}: {changed} (json)')
    if has_table(conn, 'stack_suggestion_dismissals'):
        rekeyed = rekey_dismissals(conn)
        if rekeyed:
            report.append(f'stack_suggestion_dismissals: {rekeyed} skipped suggestions re-keyed')
    if has_table(conn, 'stats_cache'):
        conn.execute('DELETE FROM stats_cache')
    if has_table(conn, 'photos_fts'):
        conn.execute("INSERT INTO photos_fts(photos_fts) VALUES('rebuild')")
    if vec:
        report.append(f"photos_vec: emptied {conn.execute('DELETE FROM photos_vec').rowcount} rows "
                      "(run database.py --populate-vec)")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('db')
    ap.add_argument('src', help='stored prefix, e.g. /data/photos')
    ap.add_argument('dst', help='new prefix, e.g. \\\\NAS\\share')
    ap.add_argument('--sep', choices=['/', '\\'], help='separator for the rest of each path '
                    '(default: the new prefix\'s own)')
    ap.add_argument('--dry-run', action='store_true', help='report what would change; write nothing')
    ap.add_argument('--no-backup', action='store_true', help='do not copy the database first')
    args = ap.parse_args()
    src, dst = trim(args.src), trim(args.dst)
    sep = args.sep or default_sep(dst)
    if src == dst:
        sys.exit('the old and new prefixes are the same')
    if nested(src, dst):
        ap.error(f'one prefix lies inside the other ({src} / {dst}): rows inserted by triggers during '
                 'the rewrite would be converted twice. Rewrite via an unrelated temporary prefix. '
                 'Nothing changed.')
    if not Path(args.db).is_file():
        sys.exit(f'no database at {args.db}')

    if not args.dry_run:
        from facet import LIBRARY_JOB_MAINTENANCE, hold_library_lock_or_exit
        hold_library_lock_or_exit(args.db, LIBRARY_JOB_MAINTENANCE)
    conn = sqlite3.connect(args.db, isolation_level=None)
    conn.execute('PRAGMA foreign_keys = OFF')
    vec = has_table(conn, 'photos_vec') and load_vec(conn)
    if has_table(conn, 'photos_vec') and not vec and not args.dry_run:
        sys.exit('photos_vec exists but sqlite-vec is not installed, so its old paths could not be '
                 'removed; install sqlite-vec (pip install sqlite-vec) and run again. Nothing changed.')
    conn.create_function('facet_rewrite', 1, lambda v: convert(v, src, dst, sep), deterministic=True)

    if not args.dry_run and not args.no_backup:
        backup = Path(f'{args.db}.before-rewrite-{time.strftime("%Y%m%d-%H%M%S")}')
        # Closed, not just committed: the backup file is released before the long write starts.
        with contextlib.closing(sqlite3.connect(backup)) as copy:
            conn.backup(copy)
        print(f'backup: {backup}')
    history = conn.execute('SELECT count(*) FROM organization_history WHERE reverted = 0').fetchone()[0] \
        if has_table(conn, 'organization_history') else 0

    fk_before = len(conn.execute('PRAGMA foreign_key_check').fetchall())
    try:
        conn.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError as exc:
        if 'locked' not in str(exc):
            raise
        sys.exit('the database is locked by another process (a running viewer?): stop the viewer and '
                 'run again. Nothing changed.')
    try:
        report = rewrite(conn, src, dst, sep, vec)
        fk_after = len(conn.execute('PRAGMA foreign_key_check').fetchall())
        if fk_after > fk_before:
            conn.execute('ROLLBACK')
            sys.exit(f'the rewrite would leave {fk_after - fk_before} new foreign-key violations. Nothing changed.')
    except sqlite3.IntegrityError as exc:
        conn.execute('ROLLBACK')
        sys.exit(f'some photos already exist under the new prefix (scanned there before?): {exc}. '
                 'Nothing changed; remove those rows or rescan instead.')
    left = conn.execute(f'SELECT count(*) FROM photos WHERE {under("path")}', (src, len(src))).fetchone()[0]
    if args.dry_run:
        conn.execute('ROLLBACK')
    else:
        conn.execute('COMMIT')
    print('\n'.join(report) if report else f'nothing stored under {src}')
    if args.dry_run:
        print('dry run: nothing written')
        return
    if history:
        print(f'undo history: {history} earlier entr{"y" if history == 1 else "ies"} can no longer be applied')
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    fk = len(conn.execute('PRAGMA foreign_key_check').fetchall())
    print('integrity:', integrity, '| foreign keys:', fk, 'violations', '| photos left on old prefix:', left)
    if integrity != 'ok' or fk > fk_before:
        sys.exit(1)


if __name__ == '__main__':
    main()
