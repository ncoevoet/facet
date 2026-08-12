"""
Tag migration functions for Facet.

Populates photo_tags lookup table from tags column.
"""

import logging
import sqlite3

from db.connection import get_connection

logger = logging.getLogger("facet.db_tags")
from db.schema import (
    _build_create_table_sql, PHOTO_TAGS_COLUMNS, PHOTO_TAGS_INDEXES,
)


def migrate_tags_to_lookup(db_path='photo_scores_pro.db', batch_size=10000):
    """
    (Re)build the photo_tags lookup table from the current tags column.

    This enables fast exact-match tag queries instead of slow LIKE '%tag%' scans.
    It is a full resync: the table is cleared first and repopulated from the live
    photos.tags values, so re-running it after tags change (rescan, XMP import,
    re-tag) drops tags no longer present and adds new ones. Appending only, as an
    earlier version did, left readers preferring a stale table with removed tags
    still in it.

    No DB backup is taken: photo_tags is a derived index fully reconstructible
    from photos.tags, and this runs under the library lock (database.py holds it
    for --migrate-tags). The previous naive ``shutil.copy2`` of the whole DB was
    WAL-unsafe (dropped the -wal/-shm sidecars) and copied the entire multi-GB
    file on every run with no disk check or rotation.

    Args:
        db_path: Path to the SQLite database file
        batch_size: Number of photos to process per batch

    Returns:
        Tuple of (total_tags_inserted, total_photos_processed)
    """
    with get_connection(db_path, row_factory=False) as conn:
        # Ensure table exists
        conn.execute(_build_create_table_sql(
            'photo_tags',
            PHOTO_TAGS_COLUMNS,
            constraints=['PRIMARY KEY (photo_path, tag)']
        ))

        # Create indexes
        for idx_name, table, column_expr in PHOTO_TAGS_INDEXES:
            conn.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})')

        # Full resync: clear the derived table so removed tags don't linger.
        conn.execute("DELETE FROM photo_tags")
        conn.commit()

        # Get total count
        total = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE tags IS NOT NULL AND tags != ''"
        ).fetchone()[0]
        logger.info("Processing %d photos with tags...", total)

        total_tags = 0
        processed = 0

        # Process in batches to avoid memory issues
        cursor = conn.execute(
            "SELECT path, tags FROM photos WHERE tags IS NOT NULL AND tags != ''"
        )

        batch = []
        for row in cursor:
            path, tags = row
            if tags:
                for tag in tags.split(','):
                    tag = tag.strip()
                    if tag:
                        batch.append((path, tag))

            processed += 1

            # Insert batch
            if len(batch) >= batch_size:
                conn.executemany(
                    "INSERT OR IGNORE INTO photo_tags (photo_path, tag) VALUES (?, ?)",
                    batch
                )
                conn.commit()
                total_tags += len(batch)
                batch = []
                logger.info("  Processed %d/%d photos (%d tags)...", processed, total, total_tags)

        # Final batch
        if batch:
            conn.executemany(
                "INSERT OR IGNORE INTO photo_tags (photo_path, tag) VALUES (?, ?)",
                batch
            )
            conn.commit()
            total_tags += len(batch)

    logger.info("Migration complete: %d tags from %d photos", total_tags, processed)
    return total_tags, processed


def get_photo_tags_count(db_path='photo_scores_pro.db'):
    """Return the number of entries in the photo_tags lookup table."""
    with get_connection(db_path, row_factory=False) as conn:
        try:
            count = conn.execute("SELECT COUNT(*) FROM photo_tags").fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
        return count
