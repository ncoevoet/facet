"""
Database maintenance functions for Facet.

VACUUM, ANALYZE, optimization, and viewer database export.
"""

import glob
import logging
import os
import shutil
import sqlite3
from datetime import datetime
from io import BytesIO

logger = logging.getLogger("facet.db_maintenance")

_PATH_PRESENT = 'present'
_PATH_DELETED = 'deleted'
_PATH_INACCESSIBLE = 'inaccessible'


def _classify_missing_path(path):
    """Classify a stored photo path as present, genuinely deleted, or merely
    inaccessible (permission denied or an unmounted/absent parent).

    A path is deletable only when its own entry is absent (``ENOENT``) and its
    parent directory exists and is readable+searchable. A ``chmod 000`` parent,
    an unreadable share, or a whole missing subtree (unmounted root) surfaces as
    ``ENOENT``/``EACCES`` and is classified inaccessible so it is preserved
    rather than cascade-deleted.
    """
    try:
        os.lstat(path)
        return _PATH_PRESENT
    except FileNotFoundError:
        pass
    except OSError:
        return _PATH_INACCESSIBLE
    parent = os.path.dirname(path) or os.sep
    try:
        os.lstat(parent)
    except OSError:
        return _PATH_INACCESSIBLE
    if not os.access(parent, os.R_OK | os.X_OK):
        return _PATH_INACCESSIBLE
    return _PATH_DELETED


def vacuum_database(db_path='photo_scores_pro.db', verbose=True):
    """Run VACUUM to reclaim space and defragment the database.

    Args:
        db_path: Path to SQLite database
        verbose: If True, print progress

    Returns:
        Tuple of (old_size, new_size) in bytes
    """
    old_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    if verbose:
        logger.info("Running VACUUM on %s...", db_path)
        logger.info("  Before: %.2f MB", old_size / 1024 / 1024)

    conn = sqlite3.connect(db_path)
    conn.execute("VACUUM")
    conn.close()

    new_size = os.path.getsize(db_path)

    if verbose:
        logger.info("  After: %.2f MB", new_size / 1024 / 1024)
        saved = old_size - new_size
        if saved > 0:
            logger.info("  Saved: %.2f MB (%.1f%%)", saved / 1024 / 1024, saved / old_size * 100)
        else:
            logger.info("  No space reclaimed (database was already compacted)")

    return old_size, new_size


def analyze_database(db_path='photo_scores_pro.db', verbose=True):
    """Run ANALYZE to update query planner statistics.

    Args:
        db_path: Path to SQLite database
        verbose: If True, print progress
    """
    if verbose:
        logger.info("Running ANALYZE on %s...", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("ANALYZE")
    conn.close()

    if verbose:
        logger.info("  Query planner statistics updated.")


def optimize_database(db_path='photo_scores_pro.db', verbose=True):
    """Run VACUUM + ANALYZE for full database optimization.

    Args:
        db_path: Path to SQLite database
        verbose: If True, print progress
    """
    if verbose:
        logger.info("Optimizing database: %s", db_path)

    vacuum_database(db_path, verbose)
    analyze_database(db_path, verbose)

    if verbose:
        logger.info("Database optimization complete.")


def check_disk_space(target_path, needed_bytes, margin=1.2):
    """Check whether the volume holding target_path has room for needed_bytes.

    Args:
        target_path: A file or directory on the volume to probe.
        needed_bytes: Raw bytes the operation is expected to write.
        margin: Safety multiplier applied to needed_bytes (default 1.2).

    Returns:
        Tuple of (ok, free_bytes, required_bytes).
    """
    probe_dir = target_path if os.path.isdir(target_path) else os.path.dirname(os.path.abspath(target_path)) or '.'
    free = shutil.disk_usage(probe_dir).free
    required = int(needed_bytes * margin)
    return free >= required, free, required


def _rotate_backups(db_path, base_dir, keep):
    """Delete the oldest backup snapshots, keeping the newest `keep`.

    Covers both the current `.backup-<ts>` (dash) and legacy `.backup.<ts>`
    (dot) naming, sorted by mtime so the two timestamp schemes still prune by
    age rather than by lexical order of their differing separators.
    """
    db_name = os.path.basename(db_path)
    patterns = (f"{db_name}.backup-*", f"{db_name}.backup.*")
    backups = sorted(
        (path for pat in patterns for path in glob.glob(os.path.join(base_dir, pat))),
        key=os.path.getmtime,
    )
    excess = backups[:-keep] if keep > 0 else backups
    for old in excess:
        try:
            os.remove(old)
        except OSError as ex:
            logger.warning("Could not remove old backup %s: %s", old, ex)


def backup_database(db_path='photo_scores_pro.db', keep=3, dest_dir=None, verbose=True):
    """Write a timestamped, WAL-safe snapshot of the DB before a destructive op.

    Uses sqlite3's online backup API, which handles the -wal/-shm sidecars
    correctly (a naive file copy would not). Old snapshots are rotated, keeping
    only the newest `keep`.

    Args:
        db_path: Path to the source SQLite database.
        keep: Number of most-recent backups to retain (older ones deleted).
        dest_dir: Directory for the backup; defaults to the DB's own directory so
            the snapshot lands on the same volume the user already sized for the DB.
        verbose: If True, log the backup path and size.

    Returns:
        The path of the backup file written.
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    source_size = os.path.getsize(db_path)
    base_dir = dest_dir or os.path.dirname(os.path.abspath(db_path))
    os.makedirs(base_dir, exist_ok=True)

    ok, free, required = check_disk_space(base_dir, source_size)
    if not ok:
        raise RuntimeError(
            f"Not enough free space to back up the database: need ~{required / 1e9:.1f} GB "
            f"(DB is {source_size / 1e9:.1f} GB), only {free / 1e9:.1f} GB free on {base_dir}"
        )

    db_name = os.path.basename(db_path)
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_path = os.path.join(base_dir, f"{db_name}.backup-{timestamp}")

    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        except BaseException:
            # A partial backup looks like a valid snapshot to a user restoring
            # one — remove it so a failed copy never leaves a misleading file.
            dst.close()
            if os.path.exists(backup_path):
                os.remove(backup_path)
            raise
        finally:
            dst.close()
    finally:
        src.close()

    _rotate_backups(db_path, base_dir, keep)

    if verbose:
        logger.info("Backed up DB to %s (%.1f GB)", backup_path, os.path.getsize(backup_path) / 1e9)
    return backup_path


def cleanup_missing_photos(db_path='photo_scores_pro.db', dry_run=False, force=False, verbose=True):
    """Delete photos from the database that are no longer on disk.

    Cascading foreign keys clean up faces, tags, comparisons, learned scores
    and per-user preferences. Stores without a cascade are cleaned explicitly
    so no orphans remain: album memberships (album_photos), album covers, and
    the sqlite-vec index (photos_vec).

    Args:
        db_path: Path to SQLite database
        dry_run: If True, only preview what would be deleted
        force: If True, delete even when every photo appears missing. Off by
            default so a temporarily unmounted volume (e.g. a NAS share) cannot
            wipe the whole database.
        verbose: If True, print progress

    Returns:
        Number of photos deleted (or that would be deleted in dry-run)
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    if verbose:
        logger.info("Checking for missing photos in %s...", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    cursor.execute("SELECT path FROM photos")
    all_paths = [row[0] for row in cursor.fetchall()]

    if verbose:
        logger.info("Found %d photos in the database. Checking filesystem...", len(all_paths))

    deleted_paths = []
    inaccessible_paths = []
    for path in all_paths:
        status = _classify_missing_path(path)
        if status == _PATH_DELETED:
            deleted_paths.append(path)
        elif status == _PATH_INACCESSIBLE:
            inaccessible_paths.append(path)

    if inaccessible_paths and verbose:
        if force:
            logger.warning(
                "%d photo(s) are on an unreadable or unmounted path — removing them "
                "anyway (--force):", len(inaccessible_paths))
        else:
            logger.warning(
                "%d photo(s) are on an unreadable or unmounted path — preserving them "
                "(re-run with --force to remove anyway):", len(inaccessible_paths))
        for p in inaccessible_paths[:10]:
            logger.warning("    %s", p)
        if len(inaccessible_paths) > 10:
            logger.warning("    ... and %d more.", len(inaccessible_paths) - 10)

    targets = deleted_paths + inaccessible_paths if force else deleted_paths

    if not targets:
        if verbose:
            if inaccessible_paths:
                logger.info("No deletable missing files — only inaccessible paths, which were preserved.")
            else:
                logger.info("No missing files found. The database is up to date.")
        conn.close()
        return 0

    if verbose:
        logger.info("Found %d photos in the database that are missing on disk.", len(targets))

    if dry_run:
        if verbose:
            logger.info("DRY RUN: The following files would be removed:")
            for p in targets[:10]:
                logger.info("  - %s", p)
            if len(targets) > 10:
                logger.info("  ... and %d more.", len(targets) - 10)
        conn.close()
        return len(targets)

    if len(targets) == len(all_paths) and not force:
        conn.close()
        raise RuntimeError(
            f"All {len(all_paths)} photos appear missing on disk — refusing to wipe the "
            "database. Check that the photo volume is mounted, preview with --dry-run, "
            "then re-run with --force if this is intended."
        )

    if verbose:
        logger.info("Removing missing files from the database (cascading deletes will clean up faces, tags, etc.)...")

    batch_size = 500
    for i in range(0, len(targets), batch_size):
        params = [(p,) for p in targets[i:i + batch_size]]
        cursor.executemany("DELETE FROM photos WHERE path = ?", params)
        # album_photos.photo_path has no ON DELETE CASCADE — drop memberships explicitly.
        cursor.executemany("DELETE FROM album_photos WHERE photo_path = ?", params)
        # An album cover may point at a now-deleted photo.
        cursor.executemany("UPDATE albums SET cover_photo_path = NULL WHERE cover_photo_path = ?", params)

    # Faces were cascade-deleted; refresh person face counts so the viewer stays accurate.
    cursor.execute(
        "UPDATE persons SET face_count = "
        "(SELECT COUNT(*) FROM faces WHERE faces.person_id = persons.id)"
    )
    emptied_persons = cursor.execute(
        "SELECT COUNT(*) FROM persons WHERE face_count = 0"
    ).fetchone()[0]

    # Invalidate stats cache since photo counts and details have changed
    try:
        cursor.execute("DELETE FROM stats_cache")
    except sqlite3.OperationalError:
        pass

    conn.commit()

    # photos_vec (sqlite-vec) has no FK or trigger. Clean it best-effort after the
    # main delete commits — the vector index is derived and rebuildable.
    from db.connection import HAS_SQLITE_VEC, load_sqlite_vec
    from db.vec import _vec_table_exists
    load_sqlite_vec(conn)
    if HAS_SQLITE_VEC and _vec_table_exists(conn):
        try:
            for i in range(0, len(targets), batch_size):
                chunk = targets[i:i + batch_size]
                placeholders = ','.join('?' * len(chunk))
                cursor.execute(f"DELETE FROM photos_vec WHERE path IN ({placeholders})", chunk)
            conn.commit()
        except sqlite3.Error as ex:
            logger.warning("Could not clean photos_vec entries (rebuild with --populate-vec): %s", ex)

    if verbose:
        logger.info("Successfully removed %d missing files from the database.", len(targets))
        if emptied_persons:
            logger.info(
                "%d person(s) now have no faces — run --cleanup-orphaned-persons to remove them.",
                emptied_persons,
            )

    conn.close()
    return len(targets)

def cleanup_orphaned_persons(db_path='photo_scores_pro.db', verbose=True):
    """Delete persons with no assigned faces.

    Args:
        db_path: Path to SQLite database
        verbose: If True, print progress

    Returns:
        Number of persons deleted
    """
    if verbose:
        logger.info("Cleaning up orphaned persons in %s...", db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count orphaned persons before deletion
    cursor.execute("""
        SELECT COUNT(*) FROM persons
        WHERE id NOT IN (SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL)
    """)
    count = cursor.fetchone()[0]

    if count > 0:
        cursor.execute("""
            DELETE FROM persons
            WHERE id NOT IN (SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL)
        """)
        conn.commit()

    conn.close()

    if verbose:
        if count > 0:
            logger.info("  Deleted %d orphaned person(s)", count)
        else:
            logger.info("  No orphaned persons found")

    return count


def _reinsert_faces(dest_conn, face_insert_cols, face_resync_paths, batch_size):
    face_select_exprs = ', '.join(
        'zeroblob(0)' if c == 'embedding'
        else 'NULL' if c == 'landmark_2d_106'
        else c
        for c in face_insert_cols
    )
    face_col_list = ', '.join(face_insert_cols)

    for i in range(0, len(face_resync_paths), batch_size):
        batch = face_resync_paths[i:i + batch_size]
        placeholders = ','.join('?' * len(batch))
        dest_conn.execute(
            f"DELETE FROM main.faces WHERE photo_path IN ({placeholders})", batch
        )
        dest_conn.execute(
            f"INSERT OR IGNORE INTO main.faces ({face_col_list}) "
            f"SELECT {face_select_exprs} FROM src.faces WHERE photo_path IN ({placeholders})",
            batch
        )
    dest_conn.commit()


def _downsize_face_thumbnails(dest_conn, face_resync_paths, thumbnail_size, batch_size):
    from PIL import Image

    face_resized = 0
    for i in range(0, len(face_resync_paths), batch_size):
        batch = face_resync_paths[i:i + batch_size]
        placeholders = ','.join('?' * len(batch))
        rows = dest_conn.execute(
            f"SELECT id, face_thumbnail FROM main.faces "
            f"WHERE photo_path IN ({placeholders}) AND face_thumbnail IS NOT NULL",
            batch
        ).fetchall()
        updates = []
        for face_id, thumb_bytes in rows:
            try:
                img = Image.open(BytesIO(thumb_bytes))
                if max(img.size) > thumbnail_size:
                    img.thumbnail((thumbnail_size, thumbnail_size), Image.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format='JPEG', quality=80)
                    updates.append((buf.getvalue(), face_id))
                    face_resized += 1
            except Exception:
                pass
        if updates:
            dest_conn.executemany(
                "UPDATE main.faces SET face_thumbnail = ? WHERE id = ?", updates
            )
            dest_conn.commit()
    return face_resized


def _incremental_update_viewer_db(source_db, output_path, thumbnail_size, verbose):
    """Incrementally sync changes from source_db into the existing viewer database.

    Processes only new/deleted photos; preserves existing thumbnails.

    Returns:
        Tuple of (source_size, output_size) in bytes
    """
    from PIL import Image

    source_size = os.path.getsize(source_db)
    if verbose:
        logger.info("  Output exists — running incremental update...")
        logger.info("  Source: %.1f MB", source_size / 1024 / 1024)

    src_escaped = source_db.replace("'", "''")
    dest_conn = sqlite3.connect(output_path)
    dest_conn.execute("PRAGMA foreign_keys = ON")
    dest_conn.execute(f"ATTACH DATABASE '{src_escaped}' AS src")

    # --- Delta detection ---
    new_paths = [r[0] for r in dest_conn.execute(
        "SELECT path FROM src.photos EXCEPT SELECT path FROM main.photos"
    ).fetchall()]
    deleted_paths = [r[0] for r in dest_conn.execute(
        "SELECT path FROM main.photos EXCEPT SELECT path FROM src.photos"
    ).fetchall()]

    if verbose:
        existing_count = dest_conn.execute("SELECT COUNT(*) FROM main.photos").fetchone()[0]
        logger.info("  Photos: %d existing, %d new, %d deleted", existing_count, len(new_paths), len(deleted_paths))

    # --- Delete removed photos (faces cascade via FK ON DELETE CASCADE) ---
    if deleted_paths:
        dest_conn.executemany(
            "DELETE FROM main.photos WHERE path = ?", [(p,) for p in deleted_paths]
        )
        dest_conn.commit()
        if verbose:
            logger.info("  Removed %d deleted photos", len(deleted_paths))

    # --- Update metadata for existing photos ---
    # Use intersection of src/dest columns to handle any schema skew gracefully
    src_photo_cols = [r[1] for r in dest_conn.execute("PRAGMA src.table_info(photos)").fetchall()]
    dest_photo_col_set = {r[1] for r in dest_conn.execute("PRAGMA main.table_info(photos)").fetchall()}
    _STRIP_COLS = {'clip_embedding', 'histogram_data', 'raw_sharpness_variance', 'caption_embedding', 'thumbnail', 'path'}
    # On-demand caches (VLM critique, caption) may be generated on the viewer
    # deployment itself, while the source scan DB keeps them NULL. COALESCE onto
    # the current destination value so a re-export never overwrites that
    # GPU-expensive cache with a NULL from source.
    _CACHE_COLS = {'vlm_critique', 'vlm_critique_translated', 'caption', 'caption_translated'}
    _RATING_COLS = {'star_rating', 'is_favorite', 'is_rejected'}
    update_cols = [c for c in src_photo_cols if c not in _STRIP_COLS and c in dest_photo_col_set]

    def _photo_set_expr(col):
        """SET expression that propagates source metadata while preserving
        viewer-side edits. Cache columns keep the destination value when source
        is NULL. A rating column keeps a *set* viewer value (non-NULL and
        non-zero: star > 0, favorite/rejected = 1), else takes the source value —
        so the first export carries the scan rating, later viewer ratings survive
        a re-export, and scan ratings still reach a never-rated photo. A rating
        cleared to 0 on the viewer is indistinguishable from unrated and cannot
        be preserved against a non-zero source."""
        src_val = f"(SELECT {col} FROM src.photos WHERE src.photos.path = main.photos.path)"
        if col in _CACHE_COLS:
            return f"{col} = COALESCE({src_val}, {col})"
        if col in _RATING_COLS:
            return (f"{col} = CASE WHEN main.photos.{col} IS NOT NULL AND main.photos.{col} != 0 "
                    f"THEN main.photos.{col} ELSE {src_val} END")
        return f"{col} = {src_val}"

    if update_cols:
        set_clause = ', '.join(_photo_set_expr(c) for c in update_cols)
        dest_conn.execute(f"UPDATE main.photos SET {set_clause}")
        dest_conn.commit()
        if verbose:
            logger.info("  Updated metadata for existing photos")

    # --- Insert new photos with stripped BLOBs and NULL thumbnail ---
    batch_size = 200
    if new_paths:
        common_photo_cols = [c for c in src_photo_cols if c in dest_photo_col_set]
        _BLOB_STRIP = {'clip_embedding', 'histogram_data', 'raw_sharpness_variance', 'caption_embedding', 'thumbnail'}
        select_exprs = ', '.join(
            f"NULL AS {c}" if c in _BLOB_STRIP else c
            for c in common_photo_cols
        )
        col_list = ', '.join(common_photo_cols)

        for i in range(0, len(new_paths), batch_size):
            batch = new_paths[i:i + batch_size]
            placeholders = ','.join('?' * len(batch))
            dest_conn.execute(
                f"INSERT OR IGNORE INTO main.photos ({col_list}) "
                f"SELECT {select_exprs} FROM src.photos WHERE path IN ({placeholders})",
                batch
            )
        dest_conn.commit()
        if verbose:
            logger.info("  Inserted %d new photos", len(new_paths))

        # Fetch and downsize thumbnails for new photos from source
        if verbose:
            logger.info("  Downsizing thumbnails for new photos to %dpx...", thumbnail_size)
        processed = 0
        for i in range(0, len(new_paths), batch_size):
            batch = new_paths[i:i + batch_size]
            placeholders = ','.join('?' * len(batch))
            rows = dest_conn.execute(
                f"SELECT path, thumbnail FROM src.photos "
                f"WHERE path IN ({placeholders}) AND thumbnail IS NOT NULL",
                batch
            ).fetchall()
            updates = []
            for path, thumb_bytes in rows:
                try:
                    img = Image.open(BytesIO(thumb_bytes))
                    if max(img.size) > thumbnail_size:
                        img.thumbnail((thumbnail_size, thumbnail_size), Image.LANCZOS)
                        buf = BytesIO()
                        img.save(buf, format='JPEG', quality=80)
                        updates.append((buf.getvalue(), path))
                    else:
                        updates.append((thumb_bytes, path))
                    processed += 1
                except Exception:
                    pass
            if updates:
                dest_conn.executemany(
                    "UPDATE main.photos SET thumbnail = ? WHERE path = ?", updates
                )
                dest_conn.commit()
        if verbose:
            logger.info("    Processed %d thumbnails", processed)

    # --- Sync faces ---
    dest_tables = {r[0] for r in dest_conn.execute(
        "SELECT name FROM main.sqlite_master WHERE type='table'"
    ).fetchall()}
    src_tables = {r[0] for r in dest_conn.execute(
        "SELECT name FROM src.sqlite_master WHERE type='table'"
    ).fetchall()}

    if 'faces' in dest_tables and 'faces' in src_tables:
        src_face_cols = [r[1] for r in dest_conn.execute("PRAGMA src.table_info(faces)").fetchall()]
        dest_face_col_set = {r[1] for r in dest_conn.execute("PRAGMA main.table_info(faces)").fetchall()}
        # Exclude 'id' so AUTOINCREMENT generates new IDs for inserted faces
        face_insert_cols = [c for c in src_face_cols if c != 'id' and c in dest_face_col_set]

        if face_insert_cols:
            face_resync_paths = [r[0] for r in dest_conn.execute(
                "SELECT p.path FROM main.photos p WHERE "
                "(SELECT COUNT(*) FROM src.faces sf WHERE sf.photo_path = p.path) != "
                "(SELECT COUNT(*) FROM main.faces df WHERE df.photo_path = p.path)"
            ).fetchall()]

            if face_resync_paths:
                _reinsert_faces(dest_conn, face_insert_cols, face_resync_paths, batch_size)
                face_resized = _downsize_face_thumbnails(
                    dest_conn, face_resync_paths, thumbnail_size, batch_size
                )
                if verbose:
                    logger.info("  Resynced faces for %d photos, downsized %d face thumbnails",
                                len(face_resync_paths), face_resized)

        # Refresh mutable per-face signals for existing faces (re-clustering,
        # recomputed blink/smile) without a full face re-insert. eyes_open_score
        # and smile_score drive the viewer's face-signal badges, so they must
        # propagate on every incremental export, not just person_id.
        _FACE_SYNC_COLS = ['person_id', 'eyes_open_score', 'smile_score']
        face_sync_cols = [c for c in _FACE_SYNC_COLS if c in src_face_cols and c in dest_face_col_set]
        if face_sync_cols:
            face_set_clause = ', '.join(
                f"{c} = (SELECT sf.{c} FROM src.faces AS sf "
                f"WHERE sf.photo_path = main.faces.photo_path "
                f"AND sf.face_index = main.faces.face_index)"
                for c in face_sync_cols
            )
            dest_conn.execute(f"UPDATE main.faces SET {face_set_clause}")
            dest_conn.commit()
            if verbose:
                logger.info("  Updated person assignments and face signals for existing faces")

    # --- Sync persons (full replace — small table) ---
    if 'persons' in dest_tables and 'persons' in src_tables:
        dest_conn.execute("DELETE FROM main.persons")
        dest_conn.execute("INSERT INTO main.persons SELECT * FROM src.persons")
        dest_conn.commit()
        if verbose:
            count = dest_conn.execute("SELECT COUNT(*) FROM main.persons").fetchone()[0]
            logger.info("  Synced %d persons", count)

    # --- Sync photo_tags (full replace — fast, no BLOBs) ---
    if 'photo_tags' in dest_tables and 'photo_tags' in src_tables:
        dest_conn.execute("DELETE FROM main.photo_tags")
        dest_conn.execute("INSERT INTO main.photo_tags SELECT * FROM src.photo_tags")
        dest_conn.commit()
        if verbose:
            count = dest_conn.execute("SELECT COUNT(*) FROM main.photo_tags").fetchone()[0]
            logger.info("  Synced %d photo_tags", count)

    # --- Sync user_preferences (multi-user per-user ratings) ---
    # Mirror the photos rating-preservation logic (F30): a per-user rating set on
    # the viewer deployment survives re-export, while scan-side ratings still reach
    # (user, photo) pairs the viewer has not rated. Rows for deleted photos cascade
    # out with the photos delete above (FK ON DELETE CASCADE, foreign_keys=ON).
    if 'user_preferences' in dest_tables and 'user_preferences' in src_tables:
        src_pref_cols = [r[1] for r in dest_conn.execute("PRAGMA src.table_info(user_preferences)").fetchall()]
        dest_pref_col_set = {r[1] for r in dest_conn.execute("PRAGMA main.table_info(user_preferences)").fetchall()}
        common_pref_cols = [c for c in src_pref_cols if c in dest_pref_col_set]
        pref_rating_cols = [c for c in common_pref_cols if c not in ('user_id', 'photo_path')]
        pref_match = ("sp.user_id = main.user_preferences.user_id "
                      "AND sp.photo_path = main.user_preferences.photo_path")
        if pref_rating_cols:
            set_clause = ', '.join(
                f"{c} = CASE WHEN main.user_preferences.{c} IS NOT NULL AND main.user_preferences.{c} != 0 "
                f"THEN main.user_preferences.{c} "
                f"ELSE (SELECT sp.{c} FROM src.user_preferences sp WHERE {pref_match}) END"
                for c in pref_rating_cols
            )
            dest_conn.execute(
                f"UPDATE main.user_preferences SET {set_clause} "
                f"WHERE EXISTS (SELECT 1 FROM src.user_preferences sp WHERE {pref_match})"
            )
        if common_pref_cols:
            col_list = ', '.join(common_pref_cols)
            dest_conn.execute(
                f"INSERT OR IGNORE INTO main.user_preferences ({col_list}) "
                f"SELECT {col_list} FROM src.user_preferences"
            )
        dest_conn.commit()
        if verbose:
            count = dest_conn.execute("SELECT COUNT(*) FROM main.user_preferences").fetchone()[0]
            logger.info("  Synced user preferences (%d rows)", count)

    # --- Clear stats_cache (viewer regenerates on demand) ---
    if 'stats_cache' in dest_tables:
        dest_conn.execute("DELETE FROM main.stats_cache")
        dest_conn.commit()

    # --- Finalize ---
    dest_conn.execute("DETACH DATABASE src")
    if verbose:
        logger.info("  Running ANALYZE...")
    dest_conn.execute("ANALYZE")
    dest_conn.close()

    output_size = os.path.getsize(output_path)
    saved = source_size - output_size
    if verbose:
        logger.info("Result:")
        logger.info("  Source:  %.1f MB", source_size / 1024 / 1024)
        logger.info("  Output:  %s (%.1f MB)", output_path, output_size / 1024 / 1024)
        if saved > 0:
            logger.info("  Saved:   %.1f MB (%.1f%%)", saved / 1024 / 1024, saved / source_size * 100)

    return source_size, output_size


def export_viewer_db(source_db='photo_scores_pro.db', output_path=None, thumbnail_size=320, verbose=True, force=False):
    """Export a lightweight database for viewer-only deployment.

    Creates a stripped-down copy suitable for low-memory NAS devices by:
    - Removing unused BLOB columns (clip_embedding, histogram_data, face embeddings)
    - Downsizing photo thumbnails from 640px to the specified size
    - Running VACUUM + ANALYZE on the result

    Args:
        source_db: Path to the source database
        output_path: Output path (default: photo_scores_viewer.db)
        thumbnail_size: Max thumbnail dimension in pixels (default: 320)
        verbose: If True, print progress
        force: If True, always do a full rebuild even if output exists

    Returns:
        Tuple of (source_size, output_size) in bytes
    """
    from PIL import Image

    if output_path is None:
        output_path = 'photo_scores_viewer.db'

    if not os.path.exists(source_db):
        raise FileNotFoundError(f"Source database not found: {source_db}")

    if os.path.abspath(source_db) == os.path.abspath(output_path):
        raise ValueError("Output path cannot be the same as source database")

    source_size = os.path.getsize(source_db)
    if verbose:
        logger.info("Exporting viewer database from %s", source_db)
        logger.info("  Source: %.1f MB", source_size / 1024 / 1024)

    # Incremental update if output already exists and force is not set
    if os.path.exists(output_path) and not force:
        return _incremental_update_viewer_db(source_db, output_path, thumbnail_size, verbose)

    # Full export: remove existing output file then do a clean backup
    if os.path.exists(output_path):
        os.remove(output_path)

    # Use sqlite3.backup() for atomic, WAL-safe copy
    if verbose:
        logger.info("  Copying database...")
    src_conn = sqlite3.connect(source_db)
    dst_conn = sqlite3.connect(output_path)
    src_conn.backup(dst_conn)
    src_conn.close()

    # Strip unused columns from the copy
    if verbose:
        logger.info("  Stripping unused BLOB columns...")

    # photos: clip_embedding, histogram_data, raw_sharpness_variance, caption_embedding
    # (caption_embedding is the scan-side moment signal, ~4.6KB/captioned photo,
    # and is never read by the viewer — stripping it keeps the export lightweight).
    dst_conn.execute("UPDATE photos SET clip_embedding = NULL, histogram_data = NULL, "
                     "raw_sharpness_variance = NULL, caption_embedding = NULL")
    dst_conn.commit()

    # faces: embedding (NOT NULL constraint — use empty blob), landmark_2d_106
    dst_conn.execute("UPDATE faces SET embedding = zeroblob(0), landmark_2d_106 = NULL")
    dst_conn.commit()

    # Downsize photo thumbnails
    if verbose:
        row = dst_conn.execute("SELECT COUNT(*) FROM photos WHERE thumbnail IS NOT NULL").fetchone()
        total = row[0]
        logger.info("  Downsizing %d thumbnails to %dpx...", total, thumbnail_size)

    try:
        from tqdm import tqdm  # noqa: F401 — import is the availability probe
        use_tqdm = True
    except ImportError:
        use_tqdm = False

    batch_size = 500
    offset = 0
    resized = 0

    while True:
        rows = dst_conn.execute(
            "SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL LIMIT ? OFFSET ?",
            (batch_size, offset)
        ).fetchall()
        if not rows:
            break

        updates = []
        for path, thumb_bytes in rows:
            if thumb_bytes is None:
                continue
            try:
                img = Image.open(BytesIO(thumb_bytes))
                if max(img.size) > thumbnail_size:
                    img.thumbnail((thumbnail_size, thumbnail_size), Image.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format='JPEG', quality=80)
                    updates.append((buf.getvalue(), path))
                    resized += 1
            except Exception:
                pass  # Skip corrupt thumbnails

        if updates:
            dst_conn.executemany("UPDATE photos SET thumbnail = ? WHERE path = ?", updates)
            dst_conn.commit()

        offset += batch_size
        if verbose and not use_tqdm:
            logger.info("    Processed %d thumbnails...", offset)

    if verbose:
        logger.info("    Resized %d thumbnails", resized)

    # Downsize face thumbnails
    if verbose:
        row = dst_conn.execute("SELECT COUNT(*) FROM faces WHERE face_thumbnail IS NOT NULL").fetchone()
        face_total = row[0]
        logger.info("  Downsizing %d face thumbnails...", face_total)

    offset = 0
    face_resized = 0

    while True:
        rows = dst_conn.execute(
            "SELECT id, face_thumbnail FROM faces WHERE face_thumbnail IS NOT NULL LIMIT ? OFFSET ?",
            (batch_size, offset)
        ).fetchall()
        if not rows:
            break

        updates = []
        for face_id, thumb_bytes in rows:
            if thumb_bytes is None:
                continue
            try:
                img = Image.open(BytesIO(thumb_bytes))
                # Face thumbnails are small; only resize if larger than thumbnail_size
                if max(img.size) > thumbnail_size:
                    img.thumbnail((thumbnail_size, thumbnail_size), Image.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format='JPEG', quality=80)
                    updates.append((buf.getvalue(), face_id))
                    face_resized += 1
            except Exception:
                pass

        if updates:
            dst_conn.executemany("UPDATE faces SET face_thumbnail = ? WHERE id = ?", updates)
            dst_conn.commit()

        offset += batch_size

    if verbose:
        logger.info("    Resized %d face thumbnails", face_resized)

    # VACUUM + ANALYZE
    if verbose:
        logger.info("  Running VACUUM...")
    dst_conn.execute("VACUUM")
    if verbose:
        logger.info("  Running ANALYZE...")
    dst_conn.execute("ANALYZE")
    dst_conn.close()

    output_size = os.path.getsize(output_path)
    saved = source_size - output_size
    if verbose:
        logger.info("Result:")
        logger.info("  Source:  %.1f MB", source_size / 1024 / 1024)
        logger.info("  Output:  %s (%.1f MB)", output_path, output_size / 1024 / 1024)
        logger.info("  Saved:   %.1f MB (%.1f%%)", saved / 1024 / 1024, saved / source_size * 100)

    return source_size, output_size
