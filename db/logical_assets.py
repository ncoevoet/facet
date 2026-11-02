"""Explicit RAW/JPEG identity. Callers own transactions and authorization scope.

Catalog-only membership never changes files or copies file-specific metadata.
The API/UI integration must preview conflicts before calling these mutations.
No photo FK: preserve legacy replacement with default nonrecursive triggers.
Current scanner UPSERT preserves membership even with recursive triggers enabled.
After file loss, a group can retain one representation or only RAWs/JPEGs;
its identity remains, and a removed primary requires a new explicit choice.
"""
from contextlib import contextmanager
import sqlite3
import uuid
from pathlib import PurePath

from utils.image_loading import JPEG_EXTENSIONS, RAW_EXTENSIONS

MAX_MEMBERS = 16


class AssetConflict(ValueError):
    """Safe refusal; no catalog mutation was accepted."""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_assets (
        id TEXT PRIMARY KEY, primary_path TEXT,
        revision INTEGER NOT NULL CHECK(revision > 0))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS logical_asset_members (
        asset_id TEXT NOT NULL REFERENCES logical_assets(id) ON DELETE CASCADE,
        photo_path TEXT NOT NULL UNIQUE, position INTEGER NOT NULL CHECK(position >= 0),
        PRIMARY KEY(asset_id,photo_path), UNIQUE(asset_id,position))''')
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_asset_primary_insert
        BEFORE INSERT ON logical_assets WHEN NEW.primary_path IS NOT NULL BEGIN
        SELECT RAISE(ABORT,'Insert membership before choosing primary'); END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_asset_primary_update
        BEFORE UPDATE OF primary_path ON logical_assets
        WHEN NEW.primary_path IS NOT NULL AND NOT EXISTS(
            SELECT 1 FROM logical_asset_members WHERE asset_id=NEW.id AND photo_path=NEW.primary_path)
        BEGIN SELECT RAISE(ABORT,'Primary must be a member'); END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_asset_member_insert
        BEFORE INSERT ON logical_asset_members WHEN NOT EXISTS(
            SELECT 1 FROM photos WHERE path=NEW.photo_path) OR NOT EXISTS(
            SELECT 1 FROM logical_assets WHERE id=NEW.asset_id)
        BEGIN SELECT RAISE(ABORT,'Member must be indexed'); END""")
    # Explicit cleanup also applies to writers with foreign_keys disabled.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_asset_delete
        AFTER DELETE ON logical_assets BEGIN
        DELETE FROM logical_asset_members WHERE asset_id=OLD.id;
        END""")
    # Keep identity while any indexed representation survives.
    # Losing a chosen primary requires a new explicit choice. Never silently
    # promote a sibling to the user's durable primary selection.
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_asset_member_delete
        AFTER DELETE ON logical_asset_members BEGIN
        UPDATE logical_assets SET revision=revision+1,
            primary_path=CASE WHEN primary_path=OLD.photo_path THEN NULL ELSE primary_path END
        WHERE id=OLD.asset_id;
        DELETE FROM logical_assets WHERE id=OLD.asset_id AND
            (SELECT COUNT(*) FROM logical_asset_members WHERE asset_id=OLD.asset_id)<1;
        END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_asset_photo_delete
        BEFORE DELETE ON photos BEGIN
        DELETE FROM logical_asset_members WHERE photo_path=OLD.path;
        END""")
    conn.execute("""CREATE TRIGGER IF NOT EXISTS logical_asset_photo_move
        AFTER UPDATE OF path ON photos WHEN OLD.path IS NOT NEW.path BEGIN
        UPDATE logical_asset_members SET photo_path=NEW.path WHERE photo_path=OLD.path;
        UPDATE logical_assets SET revision=revision+1,
            primary_path=CASE WHEN primary_path=OLD.path THEN NEW.path ELSE primary_path END
        WHERE id IN (SELECT asset_id FROM logical_asset_members WHERE photo_path=NEW.path);
        END""")


@contextmanager
def _mutation(conn):
    if not conn.in_transaction:
        raise AssetConflict('A catalog transaction is required')
    conn.execute('SAVEPOINT logical_asset_mutation')
    try:
        yield
    except BaseException:
        conn.execute('ROLLBACK TO logical_asset_mutation')
        conn.execute('RELEASE logical_asset_mutation')
        raise
    else:
        conn.execute('RELEASE logical_asset_mutation')


def _authorized(conn, paths, visibility_sql, visibility_params):
    rows = conn.execute(
        f"SELECT path FROM photos WHERE path IN ({','.join('?' for _ in paths)}) AND ({visibility_sql})",
        [*paths, *visibility_params]).fetchall()
    if {row[0] for row in rows} != set(paths):
        raise AssetConflict('Photo membership is unavailable')


def _members(conn, asset_id, revision, visibility_sql, visibility_params):
    asset = conn.execute('SELECT primary_path,revision FROM logical_assets WHERE id=?', (asset_id,)).fetchone()
    if type(revision) is not int or revision < 1 or asset is None or asset[1] != revision:
        raise AssetConflict('Photo membership changed; review again')
    paths = [row[0] for row in conn.execute(
        'SELECT photo_path FROM logical_asset_members WHERE asset_id=? ORDER BY position', (asset_id,))]
    if len(paths) < 1:
        raise AssetConflict('Photo membership is unavailable')
    _authorized(conn, paths, visibility_sql, visibility_params)
    return paths


def create(conn, paths, primary_path, *, visibility_sql, visibility_params=()):
    """Capture explicit indexed members and primary; leave all original values intact.

    Candidate relationship validation and metadata conflict acknowledgement belong
    to the caller's preview/apply contract, not filename guessing in this layer.
    """
    if (not isinstance(paths, (list, tuple)) or not 2 <= len(paths) <= MAX_MEMBERS
            or any(not isinstance(path, str) or not path or '\0' in path for path in paths)
            or len(set(paths)) != len(paths) or primary_path not in paths):
        raise AssetConflict('Choose distinct files and an explicit primary')
    extensions = {PurePath(path).suffix.lower() for path in paths}
    if (not extensions <= RAW_EXTENSIONS | JPEG_EXTENSIONS
            or not extensions & RAW_EXTENSIONS or not extensions & JPEG_EXTENSIONS):
        raise AssetConflict('Choose indexed RAW and JPEG files')
    with _mutation(conn):
        _authorized(conn, paths, visibility_sql, visibility_params)
        if conn.execute(f"SELECT 1 FROM logical_asset_members WHERE photo_path IN ({','.join('?' for _ in paths)})",
                        list(paths)).fetchone():
            raise AssetConflict('A file already belongs to a logical photo')
        asset_id = uuid.uuid4().hex
        conn.execute('INSERT INTO logical_assets VALUES (?,NULL,1)', (asset_id,))
        conn.executemany('INSERT INTO logical_asset_members VALUES (?,?,?)',
                         [(asset_id, path, position) for position, path in enumerate(paths)])
        conn.execute('UPDATE logical_assets SET primary_path=? WHERE id=?', (primary_path, asset_id))
        return asset_id


def set_primary(conn, asset_id, primary_path, revision, *, visibility_sql, visibility_params=()):
    with _mutation(conn):
        paths = _members(conn, asset_id, revision, visibility_sql, visibility_params)
        if primary_path not in paths:
            raise AssetConflict('Choose a current member as primary')
        conn.execute('UPDATE logical_assets SET primary_path=?,revision=revision+1 WHERE id=?',
                     (primary_path, asset_id))
        return revision + 1


def dissolve(conn, asset_id, revision, *, visibility_sql, visibility_params=()):
    """Restore separate indexed-photo identities; never delete underlying photos."""
    with _mutation(conn):
        _members(conn, asset_id, revision, visibility_sql, visibility_params)
        conn.execute('DELETE FROM logical_assets WHERE id=?', (asset_id,))
