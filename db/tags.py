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
    Populate the photo_tags lookup table from the existing tags column.

    This enables fast exact-match tag queries instead of slow LIKE '%tag%' scans.
    Creates a backup before migration and can be safely re-run (uses INSERT OR IGNORE).

    Args:
        db_path: Path to the SQLite database file
        batch_size: Number of photos to process per batch

    Returns:
        Tuple of (total_tags_inserted, total_photos_processed)
    """
    import shutil
    from datetime import datetime

    # Create backup first
    backup_path = f"{db_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    logger.info("Created backup: %s", backup_path)

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
