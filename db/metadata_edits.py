"""Bounded review-field edit clocks for explicit sidecar conflict detection.

One current receipt per photo/account/field, not an edit history. Triggers cover
all SQL writers; local means the writer is unknown, never a guessed actor.
"""
from contextlib import contextmanager

from db.schema import table_exists

REVIEW_FIELDS = ('star_rating', 'is_favorite', 'is_rejected', 'is_kept')


def create_review_edit_triggers(conn):
    now = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    for table, path, user in [('photos', 'path', "''"), ('user_preferences', 'photo_path', 'NEW.user_id')]:
        for field in REVIEW_FIELDS:
            values = f"NEW.{path}, {user}, '{field}', {now}, 'local'"
            update = ("changed_at=excluded.changed_at, source='local', source_path=NULL, source_at=NULL")
            statement = ("INSERT INTO photo_metadata_edits(photo_path,user_id,field,changed_at,source) "
                         f"VALUES ({values}) ON CONFLICT(photo_path,user_id,field) DO UPDATE SET {update};")
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS metadata_review_{table}_{field}_update
                AFTER UPDATE OF {field} ON {table} WHEN OLD.{field} IS NOT NEW.{field}
                BEGIN {statement} END""")
            if table == 'user_preferences':
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS metadata_review_{table}_{field}_insert
                    AFTER INSERT ON {table} WHEN COALESCE(NEW.{field},0) != 0
                    BEGIN {statement} END""")
                deleted_values = f"OLD.photo_path, OLD.user_id, '{field}', {now}, 'local'"
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS metadata_review_{table}_{field}_delete
                    AFTER DELETE ON {table} WHEN COALESCE(OLD.{field},0) != 0
                    AND EXISTS(SELECT 1 FROM photos WHERE path=OLD.photo_path)
                    BEGIN INSERT INTO photo_metadata_edits(photo_path,user_id,field,changed_at,source)
                    VALUES ({deleted_values}) ON CONFLICT(photo_path,user_id,field) DO UPDATE SET {update}; END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS metadata_review_photo_delete AFTER DELETE ON photos
        BEGIN DELETE FROM photo_metadata_edits WHERE photo_path=OLD.path; END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS metadata_review_photo_move AFTER UPDATE OF path ON photos
        BEGIN UPDATE photo_metadata_edits SET photo_path=NEW.path WHERE photo_path=OLD.path; END""")


def review_edit_state(conn, path, user_id, *, has_table=None):
    """``has_table``: a caller-held schema snapshot, so an import that
    already probed sqlite_master once does not re-probe it per photo."""
    if has_table is None:
        has_table = table_exists(conn, 'photo_metadata_edits')
    if not has_table:
        return {}
    return {row['field']: dict(row) for row in conn.execute(
        'SELECT * FROM photo_metadata_edits WHERE photo_path=? AND user_id=?', (path, user_id or ''))}


def record_sidecar_receipt(conn, path, user_id, fields, sidecar, source_at):
    """Attribute actual changed fields; trigger clocks remain the local apply time."""
    conn.executemany("UPDATE photo_metadata_edits SET source='xmp',source_path=?,source_at=? "
                     'WHERE photo_path=? AND user_id=? AND field=?',
                     [(sidecar, source_at, path, user_id or '', field) for field in fields])


def viewer_review_preserved(table, field, *, per_user=False):
    """Destination edit receipts preserve explicit zeros; legacy policy stays intact."""
    path = f'{table}.photo_path' if per_user else f'{table}.path'
    owner = f'{table}.user_id' if per_user else "''"
    fields = ('is_kept', 'is_rejected') if field in ('is_kept', 'is_rejected') else (field,)
    clock = (f"EXISTS(SELECT 1 FROM main.photo_metadata_edits me WHERE me.photo_path={path} "
             f"AND me.user_id={owner} AND me.field IN ({','.join(repr(f) for f in fields)}))")
    legacy = ' OR '.join(f'COALESCE({table}.{f},0) != 0' for f in fields)
    return f'({clock} OR {legacy})'


@contextmanager
def viewer_review_sync(conn, table):
    """Preserve destination-local receipts without copying scan-side authority.

    Replicated values are baseline data, not edits made on the viewer. Restore
    its pre-existing receipts after trigger writes inside the same savepoint.
    """
    per_user = table == 'user_preferences'
    scope = "user_id != ''" if per_user else "user_id = ''"
    columns = 'photo_path,user_id,field,changed_at,source,source_path,source_at'
    conn.execute('SAVEPOINT viewer_review_sync')
    try:
        if per_user:
            # A deleted viewer preference is a local zero reset. Recreate the
            # baseline before merging a source row; zero inserts mint no clock.
            conn.execute("INSERT OR IGNORE INTO main.user_preferences(user_id,photo_path) "
                         "SELECT DISTINCT me.user_id,me.photo_path FROM main.photo_metadata_edits me "
                         "JOIN src.user_preferences sp ON sp.user_id=me.user_id AND sp.photo_path=me.photo_path "
                         "WHERE me.user_id != ''")
        conn.execute(f'CREATE TEMP TABLE viewer_saved_edits AS SELECT {columns} '
                     f'FROM main.photo_metadata_edits WHERE {scope}')
        yield
        conn.execute(f'DELETE FROM main.photo_metadata_edits WHERE {scope}')
        conn.execute(f'INSERT INTO main.photo_metadata_edits({columns}) SELECT {columns} FROM viewer_saved_edits')
        conn.execute('DROP TABLE viewer_saved_edits')
        conn.execute('RELEASE viewer_review_sync')
    except BaseException:
        conn.execute('ROLLBACK TO viewer_review_sync')
        conn.execute('RELEASE viewer_review_sync')
        raise
