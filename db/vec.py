"""
Vector search table management for Facet.

Populates and syncs the photos_vec virtual table for sqlite-vec KNN queries.
"""

import logging
import re

from db.connection import get_connection, HAS_SQLITE_VEC
from db.schema import detect_embedding_dim

logger = logging.getLogger("facet.db_vec")

BATCH_SIZE = 5000


def _vec_table_exists(conn):
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photos_vec'"
    ).fetchone()
    return row[0] > 0


def _vec_declared_dim(conn):
    """Embedding dimension photos_vec was declared with, or None if unknown.

    Parses the stored CREATE SQL (``embedding float[NNN]``). The vec0 table
    hard-codes its dimension at creation, so an index built for one profile's
    embeddings (e.g. CLIP 768) silently rejects or mis-stores another's
    (SigLIP 1152); comparing this against the live embedding dim catches a
    profile switch.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='photos_vec'"
    ).fetchone()
    if not row or not row[0]:
        return None
    match = re.search(r'float\s*\[\s*(\d+)\s*\]', row[0], re.IGNORECASE)
    return int(match.group(1)) if match else None


def _distinct_embedding_lengths(conn):
    """Number of distinct clip_embedding byte-lengths present in photos."""
    return conn.execute(
        "SELECT COUNT(DISTINCT LENGTH(clip_embedding)) FROM photos "
        "WHERE clip_embedding IS NOT NULL"
    ).fetchone()[0]


def populate_vec_table(db_path='photo_scores_pro.db'):
    """Populate photos_vec from existing clip_embedding data.

    Creates the virtual table if it doesn't exist, detects embedding dimension
    from existing data, and bulk-inserts all embeddings.

    Returns:
        Number of embeddings inserted, or 0 if sqlite-vec is unavailable.
    """
    if not HAS_SQLITE_VEC:
        logger.warning("sqlite-vec not installed, skipping vector table population")
        return 0

    with get_connection(db_path, row_factory=False) as conn:
        dim = detect_embedding_dim(conn)
        if dim is None:
            logger.info("No embeddings found in database, nothing to populate")
            return 0

        expected_bytes = dim * 4

        # A library holding more than one embedding dimension (a half-finished
        # profile switch) can only be indexed for one of them — warn loudly
        # rather than silently indexing the majority and skipping the rest.
        if _distinct_embedding_lengths(conn) > 1:
            logger.warning(
                "photos holds multiple embedding dimensions; indexing only dim=%d. "
                "Re-run the scan under one profile so all embeddings share a space.",
                dim,
            )

        # If an existing index was built for a different dimension (profile
        # switch), drop it so it is recreated at the current dim instead of
        # freezing the old space or silently rejecting new rows.
        if _vec_table_exists(conn):
            declared = _vec_declared_dim(conn)
            if declared is not None and declared != dim:
                logger.warning(
                    "photos_vec was built for dim=%d but embeddings are now dim=%d; "
                    "dropping and rebuilding the index.", declared, dim,
                )
                conn.execute("DROP TABLE photos_vec")
                conn.commit()

        if not _vec_table_exists(conn):
            conn.execute(f'''
                CREATE VIRTUAL TABLE IF NOT EXISTS photos_vec USING vec0(
                    path TEXT PRIMARY KEY,
                    embedding float[{dim}] distance_metric=cosine
                )
            ''')
            logger.info("Created photos_vec virtual table (dim=%d)", dim)

        total = conn.execute(
            "SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL AND LENGTH(clip_embedding) = ?",
            (expected_bytes,)
        ).fetchone()[0]

        already = conn.execute("SELECT COUNT(*) FROM photos_vec").fetchone()[0]
        if already >= total:
            logger.info("photos_vec already populated (%d rows), skipping", already)
            return already

        if already > 0:
            conn.execute("DELETE FROM photos_vec")
            conn.commit()
            logger.info("Cleared %d stale rows from photos_vec", already)

        logger.info("Populating photos_vec with %d embeddings (dim=%d)...", total, dim)

        cursor = conn.execute(
            "SELECT path, clip_embedding FROM photos "
            "WHERE clip_embedding IS NOT NULL AND LENGTH(clip_embedding) = ?",
            (expected_bytes,)
        )

        inserted = 0
        batch = []
        for row in cursor:
            batch.append((row[0], row[1]))
            if len(batch) >= BATCH_SIZE:
                conn.executemany(
                    "INSERT INTO photos_vec (path, embedding) VALUES (?, ?)",
                    batch
                )
                conn.commit()
                inserted += len(batch)
                batch = []
                logger.info("  %d/%d embeddings inserted...", inserted, total)

        if batch:
            conn.executemany(
                "INSERT INTO photos_vec (path, embedding) VALUES (?, ?)",
                batch
            )
            conn.commit()
            inserted += len(batch)

        logger.info("Populated photos_vec: %d embeddings", inserted)
        return inserted


def sync_vec_row(conn, path, embedding_bytes):
    """Insert or update a single row in photos_vec.

    Called from the scoring pipeline when a new embedding is stored.
    No-op if sqlite-vec is not available or the table doesn't exist.
    """
    if not HAS_SQLITE_VEC:
        return
    if not _vec_table_exists(conn):
        return
    if embedding_bytes is None:
        return
    try:
        conn.execute("DELETE FROM photos_vec WHERE path = ?", (path,))
        conn.execute(
            "INSERT INTO photos_vec (path, embedding) VALUES (?, ?)",
            (path, embedding_bytes)
        )
    except Exception as e:
        logger.debug("Could not sync photos_vec for %s: %s", path, e)


def sync_vec_batch(conn, records):
    """Batch insert/update rows in photos_vec.

    Args:
        conn: SQLite connection (with sqlite-vec loaded)
        records: List of (path, embedding_bytes) tuples
    """
    if not HAS_SQLITE_VEC:
        return
    if not records:
        return
    if not _vec_table_exists(conn):
        return
    try:
        paths = [r[0] for r in records]
        placeholders = ','.join(['?'] * len(paths))
        conn.execute(f"DELETE FROM photos_vec WHERE path IN ({placeholders})", paths)
        conn.executemany(
            "INSERT INTO photos_vec (path, embedding) VALUES (?, ?)",
            records
        )
    except Exception as e:
        logger.debug("Could not batch sync photos_vec: %s", e)


def get_vec_count(db_path='photo_scores_pro.db'):
    """Return the number of rows in photos_vec, or 0 if unavailable."""
    if not HAS_SQLITE_VEC:
        return 0
    try:
        with get_connection(db_path, row_factory=False) as conn:
            if not _vec_table_exists(conn):
                return 0
            return conn.execute("SELECT COUNT(*) FROM photos_vec").fetchone()[0]
    except Exception:
        return 0
