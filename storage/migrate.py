"""Migrate between database and filesystem storage modes."""

import logging

from db import get_connection
from storage import FilesystemStorage

logger = logging.getLogger("facet.storage.migrate")


def migrate_to_filesystem(db_path: str, fs_path: str) -> int:
    """Export thumbnails and embeddings from DB to filesystem."""
    fs = FilesystemStorage(fs_path)

    with get_connection(db_path, row_factory=False) as conn:
        cursor = conn.execute(
            "SELECT path, thumbnail, clip_embedding FROM photos WHERE thumbnail IS NOT NULL"
        )
        count = 0
        for photo_path, thumb, embed in cursor:
            if thumb:
                fs.store_thumbnail(photo_path, thumb)
                count += 1
            if embed:
                fs.store_embedding(photo_path, embed)
            if count % 1000 == 0 and count > 0:
                logger.info("Migrated %d photos...", count)
        logger.info("Migration complete: %d thumbnails exported to %s", count, fs_path)
        return count


def migrate_to_database(db_path: str, fs_path: str) -> int:
    """Import thumbnails and embeddings from filesystem to DB."""
    fs = FilesystemStorage(fs_path)

    with get_connection(db_path, row_factory=False) as conn:
        cursor = conn.execute("SELECT path FROM photos")
        count = 0
        for (photo_path,) in cursor:
            thumb = fs.get_thumbnail(photo_path)
            if thumb:
                conn.execute(
                    "UPDATE photos SET thumbnail = ? WHERE path = ?",
                    (thumb, photo_path),
                )
                count += 1
            embed = fs.get_embedding(photo_path)
            if embed:
                conn.execute(
                    "UPDATE photos SET clip_embedding = ? WHERE path = ?",
                    (embed, photo_path),
                )
            if count % 1000 == 0 and count > 0:
                conn.commit()
                logger.info("Imported %d photos...", count)
        conn.commit()
        logger.info("Migration complete: %d thumbnails imported to database", count)
        return count
