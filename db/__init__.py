"""
Facet database package.

Re-exports public API for backwards-compatible imports.
"""

from db.connection import get_connection, apply_pragmas, DEFAULT_DB_PATH
from db.connection_pool import ConnectionPool, get_pool, get_pooled_connection
from db.schema import (
    init_database,
    PHOTOS_COLUMNS, FACES_COLUMNS, PERSONS_COLUMNS,
    PHOTO_TAGS_COLUMNS, PHOTO_TAGS_INDEXES,
    COMPARISONS_COLUMNS, COMPARISONS_INDEXES,
    LEARNED_SCORES_COLUMNS, LEARNED_SCORES_INDEXES,
    WEIGHT_OPTIMIZATION_RUNS_COLUMNS, WEIGHT_OPTIMIZATION_RUNS_INDEXES,
    STATS_CACHE_COLUMNS,
    WEIGHT_CONFIG_SNAPSHOTS_COLUMNS, WEIGHT_CONFIG_SNAPSHOTS_INDEXES,
    INDEXES,
    person_not_hidden_clause,
    _build_create_table_sql, _migrate_add_missing_columns,
)
from db.maintenance import vacuum_database, analyze_database, optimize_database, cleanup_orphaned_persons, export_viewer_db, cleanup_missing_photos, backup_database, check_disk_space
from db.stats_cache import (
    refresh_stats_cache, get_cached_stat, get_stats_cache_info,
)
from db.tags import migrate_tags_to_lookup, get_photo_tags_count
from db.vec import populate_vec_table, sync_vec_row, sync_vec_batch, get_vec_count
from db.fts import rebuild_fts, has_fts_table
from db.info import get_schema_info, get_user_version
