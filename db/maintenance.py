"""
Database maintenance functions for Facet.

VACUUM, ANALYZE, optimization, and viewer database export.
"""

import os
import sqlite3
from io import BytesIO


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
        print(f"Running VACUUM on {db_path}...")
        print(f"  Before: {old_size / 1024 / 1024:.2f} MB")

    conn = sqlite3.connect(db_path)
    conn.execute("VACUUM")
    conn.close()

    new_size = os.path.getsize(db_path)

    if verbose:
        print(f"  After: {new_size / 1024 / 1024:.2f} MB")
        saved = old_size - new_size
        if saved > 0:
            print(f"  Saved: {saved / 1024 / 1024:.2f} MB ({saved / old_size * 100:.1f}%)")
        else:
            print("  No space reclaimed (database was already compacted)")

    return old_size, new_size


def analyze_database(db_path='photo_scores_pro.db', verbose=True):
    """Run ANALYZE to update query planner statistics.

    Args:
        db_path: Path to SQLite database
        verbose: If True, print progress
    """
    if verbose:
        print(f"Running ANALYZE on {db_path}...")

    conn = sqlite3.connect(db_path)
    conn.execute("ANALYZE")
    conn.close()

    if verbose:
        print("  Query planner statistics updated.")


def optimize_database(db_path='photo_scores_pro.db', verbose=True):
    """Run VACUUM + ANALYZE for full database optimization.

    Args:
        db_path: Path to SQLite database
        verbose: If True, print progress
    """
    if verbose:
        print(f"Optimizing database: {db_path}")
        print()

    vacuum_database(db_path, verbose)
    if verbose:
        print()
    analyze_database(db_path, verbose)

    if verbose:
        print()
        print("Database optimization complete.")


def cleanup_orphaned_persons(db_path='photo_scores_pro.db', verbose=True):
    """Delete persons with no assigned faces.

    Args:
        db_path: Path to SQLite database
        verbose: If True, print progress

    Returns:
        Number of persons deleted
    """
    if verbose:
        print(f"Cleaning up orphaned persons in {db_path}...")

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
            print(f"  Deleted {count} orphaned person(s)")
        else:
            print("  No orphaned persons found")

    return count


def _incremental_update_viewer_db(source_db, output_path, thumbnail_size, verbose):
    """Incrementally sync changes from source_db into the existing viewer database.

    Processes only new/deleted photos; preserves existing thumbnails.

    Returns:
        Tuple of (source_size, output_size) in bytes
    """
    from PIL import Image

    source_size = os.path.getsize(source_db)
    if verbose:
        print(f"  Output exists — running incremental update...")
        print(f"  Source: {source_size / 1024 / 1024:.1f} MB")

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
        print(f"  Photos: {existing_count} existing, {len(new_paths)} new, {len(deleted_paths)} deleted")

    # --- Delete removed photos (faces cascade via FK ON DELETE CASCADE) ---
    if deleted_paths:
        dest_conn.executemany(
            "DELETE FROM main.photos WHERE path = ?", [(p,) for p in deleted_paths]
        )
        dest_conn.commit()
        if verbose:
            print(f"  Removed {len(deleted_paths)} deleted photos")

    # --- Update metadata for existing photos ---
    # Use intersection of src/dest columns to handle any schema skew gracefully
    src_photo_cols = [r[1] for r in dest_conn.execute("PRAGMA src.table_info(photos)").fetchall()]
    dest_photo_col_set = {r[1] for r in dest_conn.execute("PRAGMA main.table_info(photos)").fetchall()}
    _STRIP_COLS = {'clip_embedding', 'histogram_data', 'raw_sharpness_variance', 'thumbnail', 'path'}
    update_cols = [c for c in src_photo_cols if c not in _STRIP_COLS and c in dest_photo_col_set]

    if update_cols:
        set_clause = ', '.join(
            f"{c} = (SELECT {c} FROM src.photos WHERE src.photos.path = main.photos.path)"
            for c in update_cols
        )
        dest_conn.execute(f"UPDATE main.photos SET {set_clause}")
        dest_conn.commit()
        if verbose:
            print(f"  Updated metadata for existing photos")

    # --- Insert new photos with stripped BLOBs and NULL thumbnail ---
    batch_size = 200
    if new_paths:
        common_photo_cols = [c for c in src_photo_cols if c in dest_photo_col_set]
        _BLOB_STRIP = {'clip_embedding', 'histogram_data', 'raw_sharpness_variance', 'thumbnail'}
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
            print(f"  Inserted {len(new_paths)} new photos")

        # Fetch and downsize thumbnails for new photos from source
        if verbose:
            print(f"  Downsizing thumbnails for new photos to {thumbnail_size}px...")
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
            print(f"    Processed {processed} thumbnails")

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

        if new_paths and face_insert_cols:
            face_select_exprs = ', '.join(
                'zeroblob(0)' if c == 'embedding'
                else 'NULL' if c == 'landmark_2d_106'
                else c
                for c in face_insert_cols
            )
            face_col_list = ', '.join(face_insert_cols)

            for i in range(0, len(new_paths), batch_size):
                batch = new_paths[i:i + batch_size]
                placeholders = ','.join('?' * len(batch))
                dest_conn.execute(
                    f"INSERT OR IGNORE INTO main.faces ({face_col_list}) "
                    f"SELECT {face_select_exprs} FROM src.faces WHERE photo_path IN ({placeholders})",
                    batch
                )
            dest_conn.commit()

            # Downsize face thumbnails for new photo faces
            face_resized = 0
            for i in range(0, len(new_paths), batch_size):
                batch = new_paths[i:i + batch_size]
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

            if verbose:
                new_face_count = dest_conn.execute(
                    "SELECT COUNT(*) FROM main.faces WHERE photo_path IN "
                    f"(SELECT path FROM main.photos WHERE path IN ({','.join('?' * len(new_paths))}))",
                    new_paths
                ).fetchone()[0]
                print(f"  Inserted {new_face_count} new faces, downsized {face_resized} face thumbnails")

        # Update person_id for existing faces (handles re-clustering without full face re-insert)
        dest_conn.execute(
            "UPDATE main.faces SET person_id = ("
            "  SELECT person_id FROM src.faces AS sf"
            "  WHERE sf.photo_path = main.faces.photo_path AND sf.face_index = main.faces.face_index"
            ")"
        )
        dest_conn.commit()
        if verbose:
            print(f"  Updated person assignments for existing faces")

    # --- Sync persons (full replace — small table) ---
    if 'persons' in dest_tables and 'persons' in src_tables:
        dest_conn.execute("DELETE FROM main.persons")
        dest_conn.execute("INSERT INTO main.persons SELECT * FROM src.persons")
        dest_conn.commit()
        if verbose:
            count = dest_conn.execute("SELECT COUNT(*) FROM main.persons").fetchone()[0]
            print(f"  Synced {count} persons")

    # --- Sync photo_tags (full replace — fast, no BLOBs) ---
    if 'photo_tags' in dest_tables and 'photo_tags' in src_tables:
        dest_conn.execute("DELETE FROM main.photo_tags")
        dest_conn.execute("INSERT INTO main.photo_tags SELECT * FROM src.photo_tags")
        dest_conn.commit()
        if verbose:
            count = dest_conn.execute("SELECT COUNT(*) FROM main.photo_tags").fetchone()[0]
            print(f"  Synced {count} photo_tags")

    # --- Clear stats_cache (viewer regenerates on demand) ---
    if 'stats_cache' in dest_tables:
        dest_conn.execute("DELETE FROM main.stats_cache")
        dest_conn.commit()

    # --- Finalize ---
    dest_conn.execute("DETACH DATABASE src")
    if verbose:
        print("  Running ANALYZE...")
    dest_conn.execute("ANALYZE")
    dest_conn.close()

    output_size = os.path.getsize(output_path)
    saved = source_size - output_size
    if verbose:
        print(f"\nResult:")
        print(f"  Source:  {source_size / 1024 / 1024:.1f} MB")
        print(f"  Output:  {output_path} ({output_size / 1024 / 1024:.1f} MB)")
        if saved > 0:
            print(f"  Saved:   {saved / 1024 / 1024:.1f} MB ({saved / source_size * 100:.1f}%)")

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
        print(f"Exporting viewer database from {source_db}")
        print(f"  Source: {source_size / 1024 / 1024:.1f} MB")

    # Incremental update if output already exists and force is not set
    if os.path.exists(output_path) and not force:
        return _incremental_update_viewer_db(source_db, output_path, thumbnail_size, verbose)

    # Full export: remove existing output file then do a clean backup
    if os.path.exists(output_path):
        os.remove(output_path)

    # Use sqlite3.backup() for atomic, WAL-safe copy
    if verbose:
        print("  Copying database...")
    src_conn = sqlite3.connect(source_db)
    dst_conn = sqlite3.connect(output_path)
    src_conn.backup(dst_conn)
    src_conn.close()

    # Strip unused columns from the copy
    if verbose:
        print("  Stripping unused BLOB columns...")

    # photos: clip_embedding, histogram_data, raw_sharpness_variance
    dst_conn.execute("UPDATE photos SET clip_embedding = NULL, histogram_data = NULL, raw_sharpness_variance = NULL")
    dst_conn.commit()

    # faces: embedding (NOT NULL constraint — use empty blob), landmark_2d_106
    dst_conn.execute("UPDATE faces SET embedding = zeroblob(0), landmark_2d_106 = NULL")
    dst_conn.commit()

    # Downsize photo thumbnails
    if verbose:
        row = dst_conn.execute("SELECT COUNT(*) FROM photos WHERE thumbnail IS NOT NULL").fetchone()
        total = row[0]
        print(f"  Downsizing {total} thumbnails to {thumbnail_size}px...")

    try:
        from tqdm import tqdm
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
            print(f"    Processed {offset} thumbnails...")

    if verbose:
        print(f"    Resized {resized} thumbnails")

    # Downsize face thumbnails
    if verbose:
        row = dst_conn.execute("SELECT COUNT(*) FROM faces WHERE face_thumbnail IS NOT NULL").fetchone()
        face_total = row[0]
        print(f"  Downsizing {face_total} face thumbnails...")

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
        print(f"    Resized {face_resized} face thumbnails")

    # VACUUM + ANALYZE
    if verbose:
        print("  Running VACUUM...")
    dst_conn.execute("VACUUM")
    if verbose:
        print("  Running ANALYZE...")
    dst_conn.execute("ANALYZE")
    dst_conn.close()

    output_size = os.path.getsize(output_path)
    saved = source_size - output_size
    if verbose:
        print(f"\nResult:")
        print(f"  Source:  {source_size / 1024 / 1024:.1f} MB")
        print(f"  Output:  {output_path} ({output_size / 1024 / 1024:.1f} MB)")
        print(f"  Saved:   {saved / 1024 / 1024:.1f} MB ({saved / source_size * 100:.1f}%)")

    return source_size, output_size
